# vhs tape — renders the README hero GIF. Install: brew install vhs
# Run: vhs docs/launch/demo.tape   → produces docs/launch/demo.gif
Output docs/launch/demo.gif
Set FontSize 15
Set Width 1100
Set Height 640
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Type "pipx install opsroom"
Enter
Sleep 1.5s
Type "opsroom demo"
Enter
Sleep 4s
Type "opsroom sitrep"
Enter
Sleep 5s
Type "opsroom week"
Enter
Sleep 6s
