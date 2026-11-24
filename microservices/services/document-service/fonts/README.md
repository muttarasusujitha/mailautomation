Fonts for the ToC course-outline PDF, installed into the document-service image.

- `poppins/`: Poppins Regular, Medium and Bold (SIL Open Font License, `poppins/OFL.txt`), from
  [google/fonts](https://github.com/google/fonts/tree/8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5/ofl/poppins)
  at commit `8b0a1d0f`.
- Carlito, the Calibri-compatible body font, comes from the Debian package `fonts-crosextra-carlito`.

`python -m app.pdf_font_check` runs during the image build and fails it if WeasyPrint does not embed these fonts.
