"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { withBase } from "../../lib/paths";

interface School { name: string; locality: string; district: string }

function fold(value: string) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("ro").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function label(school: School) {
  return `${school.name} (${school.locality}, ${school.district})`;
}

export default function SchoolField({ value, onChange, disabled }: {
  value: string; onChange: (value: string) => void; disabled?: boolean;
}) {
  const [schools, setSchools] = useState<School[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const controller = new AbortController();
    void fetch(withBase("/schools-md.json"), { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data: { schools: School[] }) => setSchools(data.schools))
      .catch(() => { /* Manual entry remains available if the directory cannot load. */ });
    return () => controller.abort();
  }, []);

  const query = fold(value);
  const words = query.split(/\s+/);
  const matches = query.length < 2 ? [] : schools.filter((school) => {
    const text = fold(label(school));
    return words.every((word) => text.includes(word));
  }).slice(0, 8);
  const expanded = open && matches.length > 0;

  function choose(school: School) {
    onChange(label(school));
    setOpen(false);
    setActive(-1);
  }

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { setOpen(false); setActive(-1); return; }
    if (matches.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      setOpen(true);
      const index = event.key === "ArrowDown"
        ? (active + 1) % matches.length : (active <= 0 ? matches.length - 1 : active - 1);
      setActive(index);
      document.getElementById(`school-option-${index}`)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter" && expanded && active >= 0 && matches[active]) {
      event.preventDefault();
      choose(matches[active]);
    }
  }

  return (
    <div className="school-field">
      <label htmlFor="register-school">Școală / liceu / instituție</label>
      <div className="school-combobox">
        <input
          id="register-school" name="school" role="combobox" required minLength={2} maxLength={200}
          autoComplete="off" placeholder="Caută instituția sau scrie denumirea" value={value} disabled={disabled}
          aria-autocomplete="list" aria-expanded={expanded} aria-controls={expanded ? "school-options" : undefined}
          aria-activedescendant={expanded && active >= 0 ? `school-option-${active}` : undefined}
          aria-describedby="school-help" onKeyDown={keyDown}
          onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }}
          onFocus={() => setOpen(true)} onBlur={() => { setOpen(false); setActive(-1); }}
        />
        {expanded && (
          <ul id="school-options" className="school-options" role="listbox" aria-label="Instituții de învățământ">
            {matches.map((school, index) => (
              <li key={label(school)} id={`school-option-${index}`} role="option" aria-selected={active === index}
                  onMouseDown={(e) => e.preventDefault()} onClick={() => choose(school)}>
                <strong>{school.name}</strong><span>{school.locality}, {school.district}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <small id="school-help" className="muted">Caută după nume sau localitate. Dacă instituția lipsește, scrie denumirea și localitatea.</small>
    </div>
  );
}
