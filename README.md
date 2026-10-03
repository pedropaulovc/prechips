# prechips

Checks before chips. Deterministic validation of a machining process plan —
stock, setups, workholding, order of operations, DRO coordinates — against the
part's STEP geometry and one specific shop's inventory, producing a findings
report and a traveler sheet. Built for a manual mill + lathe shop with digital
positioning (cncjs + pendant + DRO emulator), not for CAM.

Plan only for now: see [PLAN.md](PLAN.md). Sample shop inventory in
[examples/inventory/pedro-shop.toml](examples/inventory/pedro-shop.toml) (sample; users supply their own).

Consumer: [harmonic-analyzer](https://github.com/pedropaulovc/harmonic-analyzer).

## DRO reference

The traveler's zero recipe uses the functions and names of the Electronica
EL400 Operation Manual (Direction §6.2, Axis Set §7.4, Preset §8.1), as
hosted by DRO PROS:

- [EL400 Operation Manual](https://www.dropros.com/documents/EL400%20OpManual.pdf)
- [Changing EL400 read direction](https://www.dropros.com/documents/400%20ScaleDirection.pdf)
- [EL400 bolt-hole circle](https://www.dropros.com/documents/EL400BoltHole.pdf), [linear hole pattern](https://www.dropros.com/documents/EL400AngleHole.pdf), [arc](https://www.dropros.com/documents/EL400Arc.pdf)

The shop's DRO is the [el400](https://github.com/pedropaulovc/el400) emulator;
where it disagrees with the manual, that is an emulator bug.
