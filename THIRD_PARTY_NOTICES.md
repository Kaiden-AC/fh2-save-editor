# Third-party notices

The editor source code is MIT-licensed (see `LICENSE`, copyright KaidenAC).
The following external material was used for research, interoperability, or
as key data.  It is **not** a copy of the editor's source code.

## ForzaTech crypto algorithm and key material

* **Doliman100 / ForzaTech-crypto-tool** (GPL-3.0) — public documentation of
  the Arxan TransformIT / TFIT layout, round structure and CBC/MAC chaining,
  and a community compilation of the Forza key/table material.
  <https://github.com/Doliman100/ForzaTech-crypto-tool>
* **ForzaCryptoTool** (the .NET tool whose embedded `LegacyTfit.bin` resource
  was used as the source of the key/table data in
  `fh2save/data/fh3_tfit.bin`).
* The original Forza crypto keys and tables were published in the XeNTaX
  community thread on Forza save encryption.

`fh2save/data/fh3_tfit.bin` contains only the FH3 Profile-context round keys,
MAC keys and the three selected TFIT table groups.  Key/table values are
factual data required to interoperate with an existing save file; they are not
creative source code.  The MIT license covers the Python implementation in
this repository, not any third-party key material.

## Format research

* **Nenkai / 010GameTemplates** — `BXML.bt` and `ProfileData.bt` binary
  templates, used as a reference for the FH3 BXML and property-bag layouts.
* **Das, Nenkai, merika, Doliman100** — authors credited on the ProfileData
  binary template.

## Games and trademarks

Forza, Forza Horizon, Xbox and related marks are trademarks of Microsoft
Corporation.  This project is unofficial and is not affiliated with or
endorsed by Microsoft, Turn 10 Studios or Playground Games.
