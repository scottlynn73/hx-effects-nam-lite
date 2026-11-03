# Reference effects: C99, no dependencies beyond libm.
#   make            build fxrender and the tests
#   make test       run every test (no hardware needed)
#   make demo       render the fixtures and Geiger's variants into out/
#   make golden     re-record Geiger's golden metrics (after an intended change)
CC ?= cc
CFLAGS ?= -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror -Wshadow -Wconversion -Wno-sign-conversion
LDLIBS = -lm

COMMON = common/fx.c common/wav.c common/signals.c
EFFECTS = geiger/geiger.c
OUT = out

all: $(OUT)/fxrender $(OUT)/test_geiger

$(OUT):
	mkdir -p $(OUT)

$(OUT)/fxrender: common/render.c $(COMMON) $(EFFECTS) common/*.h geiger/*.h | $(OUT)
	$(CC) $(CFLAGS) -o $@ common/render.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_geiger: geiger/test_geiger.c $(COMMON) $(EFFECTS) common/*.h geiger/*.h | $(OUT)
	$(CC) $(CFLAGS) -o $@ geiger/test_geiger.c $(COMMON) $(EFFECTS) $(LDLIBS)

test: all
	$(OUT)/test_geiger geiger/golden.txt
	$(OUT)/fxrender describe geiger | diff -u geiger/params.json - && echo "params.json up to date"

golden: $(OUT)/test_geiger
	$(OUT)/test_geiger --write-golden geiger/golden.txt

demo: all
	mkdir -p $(OUT)/fixtures $(OUT)/geiger
	$(OUT)/fxrender fixtures $(OUT)/fixtures
	$(OUT)/fxrender geiger $(OUT)/fixtures/chord_e.wav $(OUT)/geiger/crush.wav gain=12 rate=6000 bits=4 curve=0 tone=0.7 output=-6
	$(OUT)/fxrender geiger $(OUT)/fixtures/chord_e.wav $(OUT)/geiger/fold.wav gain=24 rate=48000 bits=16 curve=4 tone=0.9 output=-9 aa=1
	$(OUT)/fxrender geiger $(OUT)/fixtures/chord_e.wav $(OUT)/geiger/radio.wav gain=18 rate=3000 bits=6 curve=13 tone=0.35 output=-3
	@echo "demo WAVs in $(OUT)/geiger"

clean:
	rm -rf $(OUT)

.PHONY: all test golden demo clean
