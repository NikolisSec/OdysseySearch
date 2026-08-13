# Record a real demo GIF:  vhs demo.tape  (requires https://github.com/charmbracelet/vhs)
Output docs/demo.gif

Set FontSize 14
Set Width 1100
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms

Launch python odyssey.py

Sleep 2s
Type "Mr. Robot S01E01"
Sleep 500ms
Enter
Sleep 8s

# mark two rows
Space
Space
Sleep 1s

# show help
Type "?"
Sleep 2s
Escape
Sleep 500ms

# cycle sort + filter
Type "o"
Sleep 1s
Type "f"
Sleep 1s
Type "c"
Sleep 1s

Type "q"
Sleep 500ms
