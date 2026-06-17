# Recording the demo GIF

Requirements: `pip install thota-dq`, plus one of:
- [asciinema](https://asciinema.org/) + [agg](https://github.com/asciinema/agg) for GIF
- [terminalizer](https://github.com/faressoft/terminalizer) for GIF
- [vhs](https://github.com/charmbracelet/vhs) for GIF (recommended — declarative)

---

## With vhs (recommended)

Install vhs: `brew install vhs` (macOS) or see [vhs releases](https://github.com/charmbracelet/vhs/releases).

Create a `demo.tape` file in this directory:

```
Output ../../docs/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1200
Set Height 600
Set Theme "Dracula"
Set Padding 20
Set PlaybackSpeed 1.0

Type "bash run_demo.sh"
Enter
Sleep 8s
```

Then run:

```bash
vhs demo.tape
```

This produces `docs/demo.gif` directly.

---

## With asciinema

```bash
# Install: pip install asciinema
asciinema rec demo.cast
bash run_demo.sh
# Ctrl+D to stop recording
```

Convert to GIF using [agg](https://github.com/asciinema/agg):

```bash
# Install agg (Rust): cargo install --git https://github.com/asciinema/agg
agg demo.cast ../../docs/demo.gif
```

Or convert online at [asciinema.org](https://asciinema.org/) after uploading your cast.

---

## With terminalizer

```bash
# Install: npm install -g terminalizer
terminalizer record demo --skip-sharing
# Run the demo, then Ctrl+D
terminalizer render demo -o ../../docs/demo.gif
```

---

## Placing the GIF

Place the resulting `demo.gif` in the `docs/` directory at the project root and reference it in the top-level `README.md`:

```markdown
![Thota DQ Demo](docs/demo.gif)
```

---

## Tips for a clean recording

- Use a dark terminal theme (Dracula, One Dark, or Nord look great as GIFs).
- Set your terminal to 120 columns × 30 rows before recording.
- Run `clear` before starting the demo script so the recording starts clean.
- Keep the GIF under 3 MB — use `--speed 1.5` with agg or lower the frame rate in vhs if needed.
