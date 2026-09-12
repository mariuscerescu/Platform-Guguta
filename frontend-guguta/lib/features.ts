/**
 * Comutatoare de funcționalitate pentru interfața Guguță.
 *
 * Aici se dezactivează o funcție fără a o elimina: codul, contractul API și
 * testele rămân pe loc, doar comportamentul vizibil se oprește.
 */

/**
 * Referințele din răspunsul asistentului (marcajele `[1]`, `[2]` … din text și
 * lista de surse de sub răspuns).
 *
 * `false` — răspunsul se afișează ca text curat, fără referințe.
 * `true`  — revine la afișarea completă, fără nicio altă modificare.
 *
 * IMPORTANT: comutatorul controlează exclusiv AFIȘAREA. Backend-ul continuă să
 * ceară citări modelului, să le valideze (A12/A13) și să le salveze în
 * `citations`; endpointul `…/messages/{id}/citations` rămâne funcțional. De
 * aceea readucerea referințelor nu cere nicio migrare și nu pierde date.
 */
export const SHOW_ANSWER_REFERENCES = false;

/**
 * Marcaj de citare emis de model: `[1]`, `[12]`, inclusiv lipit de cuvânt
 * (`Trello[1]`) sau de alt marcaj (`[1][2]`).
 *
 * Nu atinge `[2024]` (număr de peste două cifre) și nici legăturile markdown
 * `[1](https://…)`, unde parantezele pătrate sunt eticheta unui link.
 */
const REFERENCE_MARKER = /\[(\d{1,2})\](?!\()/g;

/**
 * Scoate marcajele de citare din textul afișat, refăcând spațierea rămasă în
 * urmă („proiectului Alterego. [1] [2]" → „proiectului Alterego.").
 */
export function withoutReferenceMarkers(text: string): string {
  if (!text || !text.includes("[")) return text;
  return text
    .replace(REFERENCE_MARKER, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]+([.,;:!?])/g, "$1")
    .replace(/[ \t]+$/gm, "");
}