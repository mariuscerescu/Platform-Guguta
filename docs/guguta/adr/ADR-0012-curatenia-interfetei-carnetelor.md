# ADR-0012: Curățenia interfeței pe pagina de carnete și pe pagina carnetului

Stare: acceptat · Data: 12 septembrie 2026
Referințe: ADR-0010 (publicare sub subcale), ADR-0011 (gestionarea carnetului din
listă); `frontend-guguta/app/components/SiteHeader.tsx`,
`frontend-guguta/app/globals.css`.

## Context

Trei nepotriviri vizuale făceau cele două pagini principale să pară neîngrijite:

- **Header-ul era alb pe toate paginile.** Pe pagina de start e corect — se lipește
  de cardul alb al landing-ului. Pe celelalte pagini fundalul e `--bg` (#f7faff),
  așa că header-ul alb rămânea o bandă străină deasupra conținutului.
- **Iconița din cardul de carnet nu era centrată.** `.nb-icon` era un `span` de
  46×46px fără `display` de flex: ca element al unui container flex devenea `block`,
  deci `width`/`height` se aplicau, dar svg-ul de 20px rămânea lipit în colțul din
  stânga-sus. Măsurat înainte de corectură: pătrat 46×46 la (325, 262), svg 20×20
  la (325, 262) — exact același colț.
- **Butonul de trimitere stătea lângă caseta de scriere, nu în ea.** Caseta avea
  67px înălțime, butonul 48px, aliniate la bază: un dreptunghi mai scund, lipit de
  marginea casetei.

## Decizie

1. **Header-ul își ia culoarea după rută.** `SiteHeader` (componentă de client)
   citește `usePathname()`: pe pagina de start păstrează aspectul alb, lipit de
   cardul landing-ului (`.header-landing`); pe celelalte pagini folosește
   `background: var(--bg)`, adică exact nuanța paginii (`.header-inner`), fără
   chenar vizibil. Potrivirea rutei acceptă și forma cu `basePath`, altfel ambele
   particularități ar dispărea exact în producție, unde platforma e servită sub
   `/edu-platform`. Tot în `SiteHeader` a intrat și butonul „Intră în cont", care
   apare doar pe landing; `HeaderAuthLink` a fost șters, rămânând fără consumatori.
2. **Iconița se centrează cu flex**, iar simbolul crește la 24px (regula comună de
   20px rămâne pentru celelalte iconițe mici). `.nb-icon-sm` din vizualizarea listă
   primește același tratament.
3. **Butonul de trimitere intră în casetă:** `.composer` devine `position: relative`,
   butonul e așezat absolut în dreapta-jos (40×40, `border-radius: 50%`), iar caseta
   primește `padding-right: 62px`, ca textul să nu intre sub el. Rămâne cerc și când
   caseta crește pe verticală, pentru că e ancorat de colțul de jos.

## Consecințe

- `border` rămâne declarat (transparent) pe toate paginile, ca înălțimea header-ului
  să nu difere între landing și restul aplicației.
- Centrarea iconiței depinde de `display: flex` pe `.nb-icon`; o regulă viitoare care
  îl readuce la `inline` strică centrarea — de aceea e verificată automat, cu
  toleranță de 1px.
- Fiind așezat absolut, butonul de trimitere cere casetei `padding-right` suficient;
  altfel textul trece pe sub buton.
- Ambele pagini sunt verificate și pentru derulare pe orizontală, ca să nu rămână
  altă urmă de neîngrijire.
- Culorile se verifică prin comparație (header vs. fundalul paginii), nu prin valori
  fixe, ca o schimbare de temă să nu pice testele fără motiv.
