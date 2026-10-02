# prechips

Checks before chips. Deterministic validation of a machining process plan —
stock, setups, workholding, order of operations, DRO coordinates — against the
part's STEP geometry and one specific shop's inventory, producing a findings
report and a traveler sheet. Built for a manual mill + lathe shop with digital
positioning (cncjs + pendant + DRO emulator), not for CAM.

Plan only for now: see [PLAN.md](PLAN.md). Sample shop inventory in
[examples/inventory/pedro-shop.yaml](examples/inventory/pedro-shop.yaml) (sample; users supply their own).

Consumer: [harmonic-analyzer](https://github.com/pedropaulovc/harmonic-analyzer).
