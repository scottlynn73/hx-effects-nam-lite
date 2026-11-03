/*
 * usblog.dylib: logs every libusb call Line 6 Updater makes, for working out its
 * firmware-update protocol. Loaded with DYLD_INSERT_LIBRARIES (the Updater has no
 * hardened runtime); dyld interposing swaps the calls in every image, including
 * libcyusbserial. Nothing is changed on the wire: each call is passed straight on.
 *
 * Log lines (USBLOG=path, default /tmp/usblog.txt):
 *   <seconds> <op> key=value ... [data=<hex>]
 * Data is written in full: OUT data at submit, IN data at completion.
 *
 * build: tools/usb/build_shim.sh   (x86_64, the Updater runs under Rosetta)
 */
#include <dlfcn.h>
#include <stdarg.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

typedef struct libusb_context libusb_context;
typedef struct libusb_device libusb_device;
typedef struct libusb_device_handle libusb_device_handle;

struct libusb_device_descriptor {
    uint8_t bLength, bDescriptorType; uint16_t bcdUSB;
    uint8_t bDeviceClass, bDeviceSubClass, bDeviceProtocol, bMaxPacketSize0;
    uint16_t idVendor, idProduct, bcdDevice;
    uint8_t iManufacturer, iProduct, iSerialNumber, bNumConfigurations;
};

struct libusb_transfer;
typedef void (*libusb_transfer_cb_fn)(struct libusb_transfer *);
struct libusb_transfer {                    /* layout unchanged since libusb 1.0.0 */
    libusb_device_handle *dev_handle;
    uint8_t flags;
    unsigned char endpoint;
    unsigned char type;
    unsigned int timeout;
    int status;
    int length;
    int actual_length;
    libusb_transfer_cb_fn callback;
    void *user_data;
    unsigned char *buffer;
    int num_iso_packets;
};

/* the real functions, resolved by name through the interposed symbols */
int libusb_init(libusb_context **);
int libusb_open(libusb_device *, libusb_device_handle **);
void libusb_close(libusb_device_handle *);
int libusb_get_device_descriptor(libusb_device *, struct libusb_device_descriptor *);
int libusb_claim_interface(libusb_device_handle *, int);
int libusb_release_interface(libusb_device_handle *, int);
int libusb_reset_device(libusb_device_handle *);
int libusb_clear_halt(libusb_device_handle *, unsigned char);
int libusb_kernel_driver_active(libusb_device_handle *, int);
int libusb_control_transfer(libusb_device_handle *, uint8_t, uint8_t, uint16_t, uint16_t, unsigned char *, uint16_t, unsigned int);
int libusb_bulk_transfer(libusb_device_handle *, unsigned char, unsigned char *, int, int *, unsigned int);
int libusb_submit_transfer(struct libusb_transfer *);
int libusb_cancel_transfer(struct libusb_transfer *);
int libusb_get_string_descriptor_ascii(libusb_device_handle *, uint8_t, unsigned char *, int);
libusb_device *libusb_get_device(libusb_device_handle *);

static FILE *LOG;
static pthread_mutex_t MU = PTHREAD_MUTEX_INITIALIZER;
static double T0;

static double now(void) { struct timeval tv; gettimeofday(&tv, 0); return tv.tv_sec + tv.tv_usec / 1e6; }

static void logf_(const unsigned char *data, int n, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
static void logf_(const unsigned char *data, int n, const char *fmt, ...) {
    pthread_mutex_lock(&MU);
    if (!LOG) {
        const char *p = getenv("USBLOG");
        LOG = fopen(p && *p ? p : "/tmp/usblog.txt", "a");
        T0 = now();
        if (LOG) setvbuf(LOG, 0, _IOLBF, 1 << 16);
    }
    if (LOG) {
        fprintf(LOG, "%.6f ", now() - T0);
        va_list ap; va_start(ap, fmt); vfprintf(LOG, fmt, ap); va_end(ap);
        if (data && n > 0) {
            fputs(" data=", LOG);
            for (int i = 0; i < n; i++) fprintf(LOG, "%02x", data[i]);
        }
        fputc('\n', LOG);
        fflush(LOG);
    }
    pthread_mutex_unlock(&MU);
}

/* ---- async transfers: wrap the callback to see completions ---- */
#define NSLOT 1024
static struct { struct libusb_transfer *t; libusb_transfer_cb_fn cb; } SLOTS[NSLOT];
static pthread_mutex_t SMU = PTHREAD_MUTEX_INITIALIZER;

static int is_in(unsigned char ep) { return ep & 0x80; }

static void my_cb(struct libusb_transfer *t) {
    libusb_transfer_cb_fn cb = 0;
    pthread_mutex_lock(&SMU);
    for (int i = 0; i < NSLOT; i++) if (SLOTS[i].t == t) { cb = SLOTS[i].cb; SLOTS[i].t = 0; break; }
    pthread_mutex_unlock(&SMU);
    unsigned char *d = t->buffer; int n = t->actual_length;
    if (t->type == 0) { d += 8; }                       /* control: data follows the 8-byte setup */
    logf_(is_in(t->endpoint) || (t->type == 0 && (t->buffer[0] & 0x80)) ? d : 0, n,
          "xfer_done t=%p h=%p ep=%02x type=%u status=%d len=%d actual=%d",
          (void *)t, (void *)t->dev_handle, t->endpoint, t->type, t->status, t->length, t->actual_length);
    t->callback = cb;
    if (cb) cb(t);
}

static int my_submit(struct libusb_transfer *t) {
    int is_ctrl = t->type == 0;
    const unsigned char *d = t->buffer; int n = t->length;
    if (is_ctrl) {                                     /* setup packet, then OUT data if any */
        logf_(t->buffer, 8, "xfer_submit_ctrl t=%p h=%p len=%d setup", (void *)t, (void *)t->dev_handle, t->length);
        d += 8; n -= 8;
        if (t->buffer[0] & 0x80) n = 0;
    } else if (is_in(t->endpoint)) n = 0;
    logf_(d, n, "xfer_submit t=%p h=%p ep=%02x type=%u flags=%02x timeout=%u len=%d",
          (void *)t, (void *)t->dev_handle, t->endpoint, t->type, t->flags, t->timeout, t->length);
    if (t->callback != my_cb) {
        pthread_mutex_lock(&SMU);
        int k = -1;
        for (int i = 0; i < NSLOT; i++) if (SLOTS[i].t == t) { k = i; break; }
        if (k < 0) for (int i = 0; i < NSLOT; i++) if (!SLOTS[i].t) { k = i; break; }
        if (k >= 0) { SLOTS[k].t = t; SLOTS[k].cb = t->callback; t->callback = my_cb; }
        pthread_mutex_unlock(&SMU);
        if (k < 0) logf_(0, 0, "WARN slot table full, transfer %p not traced", (void *)t);
    }
    int r = libusb_submit_transfer(t);
    if (r) {                                           /* not submitted: undo the wrap */
        pthread_mutex_lock(&SMU);
        for (int i = 0; i < NSLOT; i++) if (SLOTS[i].t == t) { t->callback = SLOTS[i].cb; SLOTS[i].t = 0; break; }
        pthread_mutex_unlock(&SMU);
    }
    logf_(0, 0, "xfer_submit_ret t=%p r=%d", (void *)t, r);
    return r;
}

static int my_cancel(struct libusb_transfer *t) {
    int r = libusb_cancel_transfer(t);
    logf_(0, 0, "xfer_cancel t=%p r=%d", (void *)t, r);
    return r;
}

/* ---- sync calls ---- */
static int my_init(libusb_context **c) { int r = libusb_init(c); logf_(0, 0, "init r=%d", r); return r; }

static int my_get_desc(libusb_device *d, struct libusb_device_descriptor *x) {
    int r = libusb_get_device_descriptor(d, x);
    if (!r && x->idVendor == 0x0e41)
        logf_(0, 0, "device_descriptor dev=%p vid=%04x pid=%04x bcd=%04x class=%02x", (void *)d, x->idVendor, x->idProduct, x->bcdDevice, x->bDeviceClass);
    return r;
}

static int my_open(libusb_device *d, libusb_device_handle **h) {
    int r = libusb_open(d, h);
    struct libusb_device_descriptor x; memset(&x, 0, sizeof x);
    libusb_get_device_descriptor(d, &x);
    logf_(0, 0, "open dev=%p vid=%04x pid=%04x r=%d h=%p", (void *)d, x.idVendor, x.idProduct, r, r ? 0 : (void *)*h);
    return r;
}

static void my_close(libusb_device_handle *h) { logf_(0, 0, "close h=%p", (void *)h); libusb_close(h); }
static int my_claim(libusb_device_handle *h, int i) { int r = libusb_claim_interface(h, i); logf_(0, 0, "claim h=%p if=%d r=%d", (void *)h, i, r); return r; }
static int my_release(libusb_device_handle *h, int i) { int r = libusb_release_interface(h, i); logf_(0, 0, "release h=%p if=%d r=%d", (void *)h, i, r); return r; }
static int my_reset(libusb_device_handle *h) { logf_(0, 0, "reset h=%p", (void *)h); int r = libusb_reset_device(h); logf_(0, 0, "reset_ret h=%p r=%d", (void *)h, r); return r; }
static int my_clear_halt(libusb_device_handle *h, unsigned char ep) { int r = libusb_clear_halt(h, ep); logf_(0, 0, "clear_halt h=%p ep=%02x r=%d", (void *)h, ep, r); return r; }
static int my_kda(libusb_device_handle *h, int i) { int r = libusb_kernel_driver_active(h, i); logf_(0, 0, "kernel_driver_active h=%p if=%d r=%d", (void *)h, i, r); return r; }

static int my_ctrl(libusb_device_handle *h, uint8_t rt, uint8_t rq, uint16_t v, uint16_t ix, unsigned char *d, uint16_t n, unsigned int to) {
    if (!(rt & 0x80)) logf_(d, n, "ctrl_out h=%p rt=%02x rq=%02x v=%04x i=%04x len=%u to=%u", (void *)h, rt, rq, v, ix, n, to);
    int r = libusb_control_transfer(h, rt, rq, v, ix, d, n, to);
    logf_((rt & 0x80) && r > 0 ? d : 0, r, "ctrl_ret h=%p rt=%02x rq=%02x v=%04x i=%04x len=%u r=%d", (void *)h, rt, rq, v, ix, n, r);
    return r;
}

static int my_bulk(libusb_device_handle *h, unsigned char ep, unsigned char *d, int n, int *got, unsigned int to) {
    if (!(ep & 0x80)) logf_(d, n, "bulk_out h=%p ep=%02x len=%d to=%u", (void *)h, ep, n, to);
    int g = 0;
    int r = libusb_bulk_transfer(h, ep, d, n, &g, to);
    if (got) *got = g;
    logf_((ep & 0x80) ? d : 0, g, "bulk_ret h=%p ep=%02x len=%d r=%d got=%d", (void *)h, ep, n, r, g);
    return r;
}

static int my_strdesc(libusb_device_handle *h, uint8_t i, unsigned char *d, int n) {
    int r = libusb_get_string_descriptor_ascii(h, i, d, n);
    logf_(0, 0, "string_desc h=%p idx=%u r=%d s=\"%.*s\"", (void *)h, i, r, r > 0 ? r : 0, r > 0 ? (char *)d : "");
    return r;
}

#define INTERPOSE(mine, theirs) \
    __attribute__((used)) static struct { const void *a; const void *b; } _ip_##theirs \
    __attribute__((section("__DATA,__interpose"))) = { (const void *)(mine), (const void *)(theirs) }

INTERPOSE(my_init, libusb_init);
INTERPOSE(my_get_desc, libusb_get_device_descriptor);
INTERPOSE(my_open, libusb_open);
INTERPOSE(my_close, libusb_close);
INTERPOSE(my_claim, libusb_claim_interface);
INTERPOSE(my_release, libusb_release_interface);
INTERPOSE(my_reset, libusb_reset_device);
INTERPOSE(my_clear_halt, libusb_clear_halt);
INTERPOSE(my_kda, libusb_kernel_driver_active);
INTERPOSE(my_ctrl, libusb_control_transfer);
INTERPOSE(my_bulk, libusb_bulk_transfer);
INTERPOSE(my_submit, libusb_submit_transfer);
INTERPOSE(my_cancel, libusb_cancel_transfer);
INTERPOSE(my_strdesc, libusb_get_string_descriptor_ascii);
