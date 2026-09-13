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
   citește `usePathname()`: pe rutele al căror prim bloc e un card alb lipit de
   header — pagina de start, logarea și înregistrarea — folosește fundal alb cu
   exact chenarul cardului (`.header-card`, `rgba(217, 229, 244, 0.78)`), ca
   header-ul și cardul să se citească drept o singură suprafață; pe celelalte
   pagini folosește `background: var(--bg)`, adică exact nuanța paginii
   (`.header-inner`), fără chenar vizibil. Potrivirea rutei acceptă și forma cu
   `basePath`, altfel ambele particularități ar dispărea exact în producție, unde
   platforma e servită sub `/edu-platform`. Tot în `SiteHeader` a intrat și
   butonul „Intră în cont", care apare doar pe landing; `HeaderAuthLink` a fost
   șters, rămânând fără consumatori.
2. **Iconița se centrează cu flex**, iar simbolul crește la 24px (regula comună de
   20px rămâne pentru celelalte iconițe mici). `.nb-icon-sm` din vizualizarea listă
   primește același tratament.
3. **Butonul de trimitere intră în casetă:** `.composer` devine `position: relative`,
   butonul e așezat absolut în dreapta-jos (40×40, `border-radius: 50%`), iar caseta
   primește `padding-right: 62px`, ca textul să nu intre sub el. Rămâne cerc și când
   caseta crește pe verticală, pentru că e ancorat de colțul de jos.
4. **Gradientul de pe logare/înregistrare continuă din pagină în header.**
   Cardul de autentificare are două halouri (albastru la 82% 16%, verde la
   16% 82%) peste alb, iar cel albastru se scurge peste marginea de sus a
   cardului; cât timp header-ul era o bandă albă deasupra, haloul se tăia exact
   la îmbinare. Acum header-ul nu mai pictează o culoare proprie, ci chiar partea
   de sus a aceleiași suprafețe: halourile sunt declarate o dată (`--auth-glow`),
   ambele elemente le pictează cu aceeași dimensiune (`--auth-surface-h`, adică
   înălțimea header-ului plus înălțimea cardului), iar decupajul diferă exact cu
   înălțimea header-ului (`.header-auth` de la 0, `.auth-shell` de la
   `calc(-1 * var(--header-h))`). Rândul de jos al header-ului și rândul de sus
   al cardului sunt, prin construcție, rânduri vecine din aceeași imagine.

## Consecințe

- `border` rămâne declarat (transparent) pe toate paginile, ca înălțimea header-ului
  să nu difere între landing și restul aplicației.
- Rutele cu card alb dedesubt sunt enumerate explicit (`CARD_ROUTES` în
  `SiteHeader`). La prima versiune lista avea doar pagina de start, iar pe
  logare și înregistrare header-ul lua `--bg`: măsurat, header
  `rgb(247, 250, 255)` peste card `rgb(255, 255, 255)`, lipite la y=90 — o dungă
  albastră între două suprafețe care ar trebui să pară una singură. O pagină nouă
  care începe cu un card alb trebuie adăugată în listă, altfel revine dunga.
- Chenarul header-ului are exact culoarea chenarului cardurilor
  (`rgba(217, 229, 244, 0.78)`) și laturile se continuă; cardul nu are chenar de
  sus, deci verificarea compară laturile, nu muchia de sus (care, lipsind,
  preia culoarea textului).
- Îmbinarea gradientului depinde de trei lucruri: aceeași lățime la ambele
  elemente, `--header-h` egal cu înălțimea reală a header-ului și cele 12px de
  sus plus 12px de jos incluse în `--auth-surface-h`. Dacă se schimbă înălțimea
  header-ului sau marginile, imaginea se decalează și muchia reapare.
- `background-attachment: fixed` ar fi fost o soluție mai scurtă, dar ar fi rupt
  derularea normală (haloul ar fi rămas lipit de fereastră) și nu e respectată
  uniform de browsere; decupajul explicit nu depinde de comportamentul browserului.
- Dovada nu se face doar pe stiluri calculate: `verify-gradient-header.mjs`
  decupează o fâșie de 25 de pixeli peste linia de îmbinare, o decodează în
  browser (prin canvas) și compară saltul de culoare de la muchie cu salturile
  dintre rândurile vecine. Măsurat: salt 0–1 la mijloc și în stânga, 1 sub haloul
  albastru — exact cât între rândurile vecine, deci nicio muchie vizibilă.
- Centrarea iconiței depinde de `display: flex` pe `.nb-icon`; o regulă viitoare care
  îl readuce la `inline` strică centrarea — de aceea e verificată automat, cu
  toleranță de 1px.
- Fiind așezat absolut, butonul de trimitere cere casetei `padding-right` suficient;
  altfel textul trece pe sub buton.
- Ambele pagini sunt verificate și pentru derulare pe orizontală, ca să nu rămână
  altă urmă de neîngrijire.
- Culorile se verifică prin comparație (header vs. fundalul paginii), nu prin valori
  fixe, ca o schimbare de temă să nu pice testele fără motiv.
