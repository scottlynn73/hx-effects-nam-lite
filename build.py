#!/usr/bin/env python3
"""One command for each HX Effects build. Each builds the image, then checks it with the repo's verifier;
only an image that ends "ALL OK" should be flashed.

usage: python3 build.py nam|full [--quick] [-- extra options for the builder]

  nam    NAM A2 Lite + Click                      build_nam_click.py --nam-host regal
  full   NAM A2 Lite + Click + the extra effects  build_all.py
         (Geiger, Commander, Corrupt, Ottobit, Doom Chug)

NAM sits on the mono Regal Bass DI (Distortion > Mono) in both, so a cab IR can follow it.
Before the build, build_effects.py and build_click.py make the single NAM and Click images the verifiers
compare against; --quick skips them when they already exist. Options after -- go to the builder, e.g.
`python3 build.py full -- --with commander` (fewer effects) or `python3 build.py nam -- --nam-host ir`.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
MODES = {
    'nam': (['build_nam_click.py', '--nam-host', 'regal'], 'tools/verify/verify_nam_click.py'),
    'full': (['build_all.py'], 'tools/verify/verify_all.py'),
}
REFS = [('build_effects.py', 'build/HX_Effects_v3.80.0_NAM_A2_Lite.hxf'),
        ('build_click.py', 'build/HX_Effects_v3.80.0_Click.hxf')]


def step(args, quiet=True):
    print('$ python3 ' + ' '.join(args), flush=True)
    r = subprocess.run([PY, *args], cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        sys.stdout.write(r.stdout[-4000:])
        sys.stderr.write(r.stderr[-4000:])
        sys.exit(f'build.py: {args[0]} failed')
    if not quiet:
        sys.stdout.write(r.stdout)
    return r.stdout


def main():
    argv = sys.argv[1:]
    extra = argv[argv.index('--') + 1:] if '--' in argv else []
    argv = argv[:argv.index('--')] if '--' in argv else argv
    if not argv or argv[0] not in MODES or '-h' in argv or '--help' in argv:
        sys.exit(__doc__)
    mode = argv[0]
    builder, verifier = MODES[mode]
    for script, image in REFS:
        if '--quick' in argv and os.path.isfile(os.path.join(HERE, image)):
            print(f'(--quick: using the existing {image})')
            continue
        step([script])
    if '--nam-host' in extra and '--nam-host' in builder:   # an option given after -- replaces the mode's own
        k = builder.index('--nam-host')
        builder = builder[:k] + builder[k + 2:]
    log = step(builder + extra)
    man = next((ln.split('manifest', 1)[1].strip() for ln in log.splitlines() if ln.startswith('[+] manifest')), None)
    out = next(ln.split('Done:', 1)[1].strip() for ln in log.splitlines() if ln.startswith('Done:'))
    report = step([verifier] + ([man] if man else []), quiet=False)
    md5 = hashlib.md5(open(out, 'rb').read()).hexdigest()
    rel = os.path.relpath(out, HERE)
    if 'ALL OK' not in report.splitlines()[-1]:
        sys.exit(f'\nbuild.py: {rel} FAILED verification: do not flash it.')
    print(f'\n{mode}: {rel}\nMD5 {md5}, verified ALL OK\n'
          f'Flash: echo flash | .venv/bin/python tools/flash.py flash {rel}')


if __name__ == '__main__':
    main()
