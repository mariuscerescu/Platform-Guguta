"use client";

import { useEffect, useState } from "react";

const MESSAGES = [
  "Mă gândesc…",
  "Mă uit prin materiale…",
  "Pun ideile cap la cap…",
  "Caut o explicație cât mai clară…",
  "Pregătesc răspunsul…",
  "Încă un pic…",
];

export function useChatWaitingMessage(active: boolean): string {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
    if (!active) return;
    const timer = window.setInterval(() => setIndex(value => (value + 1) % MESSAGES.length), 4000);
    return () => window.clearInterval(timer);
  }, [active]);

  return MESSAGES[index];
}
