#!/bin/zsh
# Re-run of the v3.3 install-force analyses at another design point (v3.4 assembly_card.DESIGN_FORCES).
# usage: run.sh <du> <weight_g>     e.g. run.sh 2.45 105.1 (v3.4 as built); run.sh 1.75 102.477 gives the v3.3 numbers
# Writes the JSON files next to the scripts. Python: the project venv (override with PY=...).
cd "$(dirname "$0")"
PY=${PY:-../../../.venv/bin/python}
export FORCES_DU=$1 FORCES_WEIGHT_G=$2
for s in tabs4/study_install.py tabs4/study_install_extra.py tabs4/peel_estimate.py review/install_lift.py; do
  $PY -I $s > /dev/null || { echo "FAILED $s"; exit 1; }
done
echo "done: du $1, weight $2 g"
