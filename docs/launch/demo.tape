# vhs tape — renders the README hero GIF. Install: brew install vhs
# Run from repo root: vhs docs/launch/demo.tape   → produces docs/launch/demo.gif
# Uses the fictional `opsroom demo` portfolio (555 numbers, .example domains).
Output docs/launch/demo.gif
Set FontSize 15
Set Width 1100
Set Height 640
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Shell "bash"

Hide
Type `export PATH="$PWD/.venv/bin:$PATH" OPSROOM_NO_OPEN=1`
Enter
Type `export OPSROOM_CONFIG_DIR=~/.local/share/opsroom/demo/config OPSROOM_DATA_DIR=~/.local/share/opsroom/demo/data`
Enter
Type "clear"
Enter
Show

Type "opsroom demo"
Enter
Sleep 3.5s
Type "opsroom sitrep"
Enter
Sleep 5s
Type "opsroom week"
Enter
Sleep 6.5s
