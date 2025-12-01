# NightVisionFilterTool

Made this to play Tarkov in the night without night visors. Based on Windows API, works with both Nvidia and AMD graphic cards.

## Support my work

Your support is greatly appreciated and helps me keep improving the tool.

[![Buy Me A Coffee](https://cdn.buymeacoffee.com/buttons/default-orange.png)](https://www.buymeacoffee.com/zeroxpapone)

## How to use

* Download the .exe file from the [Releases page](https://github.com/zeroxpapone/NightVisionFilterTool/releases) and run it. Configuration files (`settings.json` and `presets.json`) will be auto-created in the same directory.
* I recommend checking that the default values suit your tastes as I cannot guarantee that they will work well on all monitors. Hop on an offline raid to check them out.
* The shortcut to toggle "filters" on/off is **CTRL + F10** by default. It can be changed through the Settings panel (v2.0 and above).
* **Save your favorite settings as presets** for quick access! Click "💾 Save Current" in the Presets section to create a new preset, then load it anytime with a single click.
* Use the "⚙️ Manage" button to rename or delete existing presets.

## Streamdeck - MacroButtons compatible (v1.1 and later)

* If you plan on using this tool with Elgato Streamdeck, just set a button to run the .exe file. If the program is not running, it will be launched. If it's already running, it will toggle the "filters" the same way as the shortcut does.
* If you plan on using VM MacroButtons instead (as I do), configure a button to have this as "Request for Button ON / Trigger IN:" -> System.Execute("PATH TO NVFT.exe","","");
* MacroButtons is useful if you already use VoiceMeeter with an external MIDI device (again, as I do) so you can assign a MIDI control to it (bottom left side of the Button Configuration -> M.I.D.I. Implementation -> Learn (From MIDI mapping device)).

## Contacts

I don't plan to maintain the project long-term unless I receive requests or reports from users. If you have anything to report or request, please dm me on [Discord](https://discord.com/users/402818359185506304).

## License

Distributed under the **GNU General Public License v3.0**. See `LICENSE` for more information.

**Disclaimer:** This software is provided **"as is"**, without warranty of any kind, express or implied. The authors are not responsible for any hardware damage, data loss, or **game account bans** resulting from the use of this tool. Use it at your own risk.
