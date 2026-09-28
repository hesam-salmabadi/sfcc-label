# Classification — open items

Model `sfcc-joint-1.1` is developed and evaluated for the **topsoil class (2.5 cm < depth < 7.5 cm, plus 0–5 cm integrating probes)** only.
`sfcc-label classify` processes that class by default. Items below are deliberately postponed.

## Depth
- **Surface skin (0 ≤ depth < 2 cm, 197 sensors):** evaluate whether the priors (frozen fraction, width), the
  slow-freeze cut-off and the fallback averages hold for sensors at or near the surface before running it
  (`--depth-class skin` exists but is not validated).
- **Sensors at 2–2.5 cm:** the 291 ISMN probes integrating 0–5 cm are in topsoil (decided 2026-09-28); the 56
  point sensors at exactly 2.5 cm (55 AmeriFlux, 1 BERMS) and sensors at 2–2.5 cm stay out for now.
- **Deeper sensors (≥ 7.5 cm, about 10,600 sensors):** define depth classes, check the method per class, run.
- **Sensors without a depth (332):** decide whether any can be assigned a class.

## Method
- **Cross-probe uncertainty (± 0.16 °C)** was measured only at James Bay (TEROS12 vs iButton). Check other
  probe pairs if co-located records become available.
- **Gradual-onset soils:** documented limitation (T_on may be 0.1–0.7 °C colder than a logistic fit in the
  ~16 % of winters where that shape fits better; real examples mostly reflect uneven data above 0 °C).
- **Soil-based frozen-level prior (`SoilPrior`):** kept but not used; revisit after the full run.

## Before the full topsoil run
- Decision log (every method choice with its evidence) — pending.
- Workflow chart in the manuscript — pending.
- Commit the code so the run manifest records a clean commit.
