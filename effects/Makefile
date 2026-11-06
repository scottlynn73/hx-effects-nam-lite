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
EFFECTS = geiger/geiger.c metronome/metronome.c commander/commander.c corrupt/corrupt.c ottobit/ottobit.c stutter/stutter.c syntax/syntax.c grains/grains.c sequence/sequence.c warp/warp.c
HEADERS = common/*.h geiger/*.h metronome/*.h commander/*.h corrupt/*.h ottobit/*.h stutter/*.h syntax/*.h grains/*.h sequence/*.h warp/*.h
OUT = out

all: $(OUT)/fxrender $(OUT)/test_geiger $(OUT)/test_metronome $(OUT)/test_commander $(OUT)/test_corrupt $(OUT)/test_ottobit $(OUT)/test_stutter $(OUT)/test_syntax $(OUT)/test_grains $(OUT)/test_sequence $(OUT)/test_warp

$(OUT):
	mkdir -p $(OUT)

$(OUT)/fxrender: common/render.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ common/render.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_geiger: geiger/test_geiger.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ geiger/test_geiger.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_metronome: metronome/test_metronome.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ metronome/test_metronome.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_commander: commander/test_commander.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ commander/test_commander.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_corrupt: corrupt/test_corrupt.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ corrupt/test_corrupt.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_ottobit: ottobit/test_ottobit.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ ottobit/test_ottobit.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_stutter: stutter/test_stutter.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ stutter/test_stutter.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_syntax: syntax/test_syntax.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ syntax/test_syntax.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_grains: grains/test_grains.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ grains/test_grains.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_sequence: sequence/test_sequence.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ sequence/test_sequence.c $(COMMON) $(EFFECTS) $(LDLIBS)

$(OUT)/test_warp: warp/test_warp.c $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -o $@ warp/test_warp.c $(COMMON) $(EFFECTS) $(LDLIBS)

# the reference as a shared library, for the SHARC kernels' checks (ctypes)
$(OUT)/libfx.so: $(COMMON) $(EFFECTS) $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -shared -fPIC -o $@ $(COMMON) $(EFFECTS) $(LDLIBS)

sharc-check: $(OUT)/libfx.so
	../.venv/bin/python3 metronome/sharc/click_kernel.py --check
	../.venv/bin/python3 metronome/sharc/click_kernel.py --check --place b3 --seconds 0.5
	../.venv/bin/python3 geiger/sharc/geiger_kernel.py --check --seconds 0.25
	../.venv/bin/python3 commander/sharc/commander_kernel.py --check --seconds 0.25
	../.venv/bin/python3 corrupt/sharc/corrupt_kernel.py --check --seconds 0.25
	../.venv/bin/python3 corrupt/sharc/commander_corrupt_kernel.py --check --seconds 0.25
	../.venv/bin/python3 ottobit/sharc/ottobit_kernel.py --check --seconds 0.25
	../.venv/bin/python3 stutter/sharc/stutter_kernel.py --check --seconds 0.25
	../.venv/bin/python3 syntax/sharc/syntax_kernel.py --check --seconds 0.25
	../.venv/bin/python3 grains/sharc/grains_kernel.py --check --seconds 0.25
	../.venv/bin/python3 sequence/sharc/sequence_kernel.py --check --seconds 0.25
	../.venv/bin/python3 warp/sharc/warp_kernel.py --check --seconds 0.25

test: all
	$(OUT)/test_geiger geiger/golden.txt
	$(OUT)/test_metronome
	$(OUT)/test_commander
	$(OUT)/test_corrupt
	$(OUT)/test_ottobit
	$(OUT)/test_stutter
	$(OUT)/test_syntax
	$(OUT)/test_grains
	$(OUT)/test_sequence
	$(OUT)/test_warp
	$(OUT)/fxrender describe warp | diff -u warp/params.json - && echo "warp params.json up to date"
	$(OUT)/fxrender describe sequence | diff -u sequence/params.json - && echo "sequence params.json up to date"
	$(OUT)/fxrender describe grains | diff -u grains/params.json - && echo "grains params.json up to date"
	$(OUT)/fxrender describe syntax | diff -u syntax/params.json - && echo "syntax params.json up to date"
	$(OUT)/fxrender describe stutter | diff -u stutter/params.json - && echo "stutter params.json up to date"
	$(OUT)/fxrender describe ottobit | diff -u ottobit/params.json - && echo "ottobit params.json up to date"
	$(OUT)/fxrender describe corrupt | diff -u corrupt/params.json - && echo "corrupt params.json up to date"
	$(OUT)/fxrender describe commander | diff -u commander/params.json - && echo "commander params.json up to date"
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
	$(OUT)/fxrender metronome $(OUT)/fixtures/chord_e.wav $(OUT)/metronome/click_4-4.wav time=0.5 meter=4 level=0.4
	$(OUT)/fxrender metronome $(OUT)/fixtures/silence.wav $(OUT)/metronome/wood_3-4_eighths.wav time=0.436364 meter=3 sound=1 subdiv=2 level=0.7
	$(OUT)/fxrender metronome $(OUT)/fixtures/silence.wav $(OUT)/metronome/beep_5-4.wav time=0.666667 meter=5 sound=2 level=0.6
	@echo "demo WAVs in $(OUT)/geiger and $(OUT)/metronome"

clean:
	rm -rf $(OUT)

.PHONY: all test golden demo clean sharc-check
