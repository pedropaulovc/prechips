#!/bin/bash
# usage: pilots.sh <outroot>
cd C:/src/prechips-rv-compose/scratch
export FREECAD_CMD="C:/Users/pedro/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" PRECHIPS_KERNEL_CACHE=C:/src/kcache-rv-compose PRECHIPS_REQUIRE_KERNEL=1
P=C:/src/prechips-rv-compose/.venv/Scripts/prechips.exe
E=C:/src/prechips-rv-compose/examples
OUT=${1:-C:/src/prechips-rv-compose/scratch/out}
mkdir -p "$OUT"
for spec in pivot-shaft:pivot-shaft/plan.toml rocker-arm:rocker-arm/plan.toml pivot-bracket:pivot-bracket/plan.toml cone-pivot-post:cone-pivot-post/built-up.toml; do
  n=${spec%%:*}; f=${spec#*:}
  $P check $E/$f > $OUT-$n-check.log 2>&1; c=$?
  $P traveler $E/$f --out $OUT/$n > $OUT-$n-traveler.log 2>&1; t=$?
  echo "$n check=$c traveler=$t"
done
