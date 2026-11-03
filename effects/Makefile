# Reference effects: C99, no dependencies beyond libm.
#   make            build fxrender and the tests
#   make test       run every test (no hardware needed)
#   make demo       render the fixtures and Geiger's variants into out/
#   make golden     re-record Geiger's golden metrics (after an intended change)
#   make sharc-check  run the SHARC kernels in the simulator against the reference (bit for bit)
CC ?= cc
CFLAGS ?= -std=c99 -O2 -ffp-contract=off -Wall -Wextra -Wpedantic -Werror -Wshadow -Wconversion -Wno-sign-conversion
LDLIBS = -lm

COMMON = common/fx.c common/wav.c common/signals.c
EFFECTS = geiger/geiger.c metronome/metronome.c
HEADERS = common/*.h geiger/*.h metronome/*.h
OUT = out

all: $(OUT)/fxrender $(OUT)/test_geiger $(OUT)/test_metronome

$(OUT):
	mkdir -p $(OUT)

$(OUT)/fxrender: common/render.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ common/render.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_geiger: geiger/test_geiger.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ geiger/test_geiger.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_metronome: metronome/test_metronome.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ metronome/test_metronome.c $(COMMON) $(EFFECTS) $(LDLIBS)

# the reference as a shared library, for the SHARC kernels' checks (ctypes)
$(OUT)/libfx.so: $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $(COMMON) $(EFFECTS) $(LDLIBS)

sharc-check: $(OUT)/libfx.so
	../.venv/bin/python3 metronome/sharc/click_kernel.py --check

test: all
	$(OUT)/test_geiger geiger/golden.txt
	$(OUT)/test_metronome
	$(OUT)/fxrender describe metronome | diff -u metronome/params.json - && echo "metronome params.json up to date"
	$(OUT)/fxrender describe geiger | diff -u geiger/params.json - && echo "params.json up to date"

golden: $(OUT)/test_geiger
	$(OUT)/test_geiger --write-golden geiger/golden.txt

demo: all
	mkdir -p $(OUT)/fixtures $(OUT)/geiger
	$(OUT)/fxrender fixtures $(OUT)/fixtures
	$(OUT)/fxrender geiger $(OUT)/fixtures/chord_e.wav $(OUT)/geiger/crush.wav gain=12 rate=6000 bits=4 curve=0 tone=0.7 output=-6
	$(OUT)/fxrender geiger $(OUT)/fixtures/chord_e.wav $(OUT)/geiger/fold.wav gain=24 rate=48000 bits=16 curve=4 tone=0.9 output=-9 aa=1
	$(OUT)/fxrender geiger $(OUT)/fixtures/chord_e.wav $(OUT)/geiger/radio.wav gain=18 rate=3000 bits=6 curve=13 tone=0.35 output=-3
	mkdir -p $(OUT)/metronome
	$(OUT)/fxrender metronome $(OUT)/fixtures/chord_e.wav $(OUT)/metronome/click_4-4.wav tempo=120 meter=4 level=0.4
	$(OUT)/fxrender metronome $(OUT)/fixtures/silence.wav $(OUT)/metronome/wood_3-4_eighths.wav tempo=137 meter=3 sound=1 subdiv=2 level=0.7
	$(OUT)/fxrender metronome $(OUT)/fixtures/silence.wav $(OUT)/metronome/beep_5-4.wav tempo=90 meter=5 sound=2 level=0.6
	@echo "demo WAVs in $(OUT)/geiger and $(OUT)/metronome"

clean:
	rm -rf $(OUT)

.PHONY: all test golden demo clean sharc-check
