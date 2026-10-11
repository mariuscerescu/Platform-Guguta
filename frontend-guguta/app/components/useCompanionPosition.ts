"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent } from "react";

const EDGE = 8;
type Position = { x: number; y: number };
type Drag = { pointerId: number; startX: number; startY: number; lastX: number; offsetX: number; offsetY: number; active: boolean };
const unit = (value: number) => Math.min(1, Math.max(0, value));

/** A dragged position belongs only to the current page and resets on navigation. */
export function useCompanionPosition(scope: string) {
  const container = useRef<HTMLElement | null>(null);
  const [node, setNode] = useState<HTMLElement | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [dragging, setDragging] = useState(false);
  const [dragDirection, setDragDirection] = useState<"running-left" | "running-right" | null>(null);
  const drag = useRef<Drag | null>(null);
  const [geometry, setGeometry] = useState({ width: 280, height: 520, viewportWidth: 0, viewportHeight: 0 });

  const setContainer = useCallback((element: HTMLElement | null) => {
    container.current = element;
    setNode(element);
  }, []);

  const update = useCallback((value: Position | null) => {
    setPosition(value);
  }, []);

  useLayoutEffect(() => {
    drag.current = null;
    setDragging(false);
    setDragDirection(null);
    update(null);
  }, [scope, update]);

  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => {
      const bounds = node.getBoundingClientRect();
      const next = { width: bounds.width, height: bounds.height, viewportWidth: window.innerWidth, viewportHeight: window.innerHeight };
      setGeometry(previous => Object.keys(next).every(key => previous[key as keyof typeof next] === next[key as keyof typeof next]) ? previous : next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    window.addEventListener("resize", measure);
    return () => { observer.disconnect(); window.removeEventListener("resize", measure); };
  }, [node]);

  const moveTo = useCallback((left: number, top: number) => {
    const bounds = container.current?.getBoundingClientRect();
    if (!bounds) return;
    const xSpace = Math.max(0, window.innerWidth - bounds.width - EDGE * 2);
    const ySpace = Math.max(0, window.innerHeight - bounds.height - EDGE * 2);
    update({ x: xSpace ? unit((left - EDGE) / xSpace) : 0, y: ySpace ? unit((top - EDGE) / ySpace) : 0 });
  }, [update]);

  useEffect(() => {
    const onMove = (event: globalThis.PointerEvent) => {
      const pending = drag.current;
      if (!pending || pending.pointerId !== event.pointerId) return;
      if (!pending.active && Math.hypot(event.clientX - pending.startX, event.clientY - pending.startY) < 5) return;
      pending.active = true;
      const deltaX = event.clientX - pending.lastX;
      pending.lastX = event.clientX;
      if (Math.abs(deltaX) > 1) setDragDirection(deltaX < 0 ? "running-left" : "running-right");
      setDragging(true);
      event.preventDefault();
      moveTo(event.clientX - pending.offsetX, event.clientY - pending.offsetY);
    };
    const finish = (event?: globalThis.PointerEvent) => {
      if (!drag.current || (event && event.pointerId !== drag.current.pointerId)) return;
      drag.current = null;
      setDragging(false);
      setDragDirection(null);
    };
    const onBlur = () => finish();
    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("blur", onBlur);
      drag.current = null;
      setDragDirection(null);
    };
  }, [moveTo]);

  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (!event.isPrimary || event.button !== 0 || drag.current) return;
    const path = event.nativeEvent.composedPath();
    const handle = path.some(target => target instanceof HTMLElement && target.hasAttribute("data-companion-drag-handle"));
    const stage = path.some(target => target instanceof HTMLElement && (target.getAttribute("part") === "stage" || target.getAttribute("part") === "mascot"));
    if (!handle && !stage) return;
    if (!handle && path.some(target => target instanceof HTMLElement && target.matches("button, select, input, textarea, a, summary, [contenteditable]"))) return;
    const bounds = container.current?.getBoundingClientRect();
    if (!bounds) return;
    setDragDirection(null);
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, lastX: event.clientX, offsetX: event.clientX - bounds.left, offsetY: event.clientY - bounds.top, active: false };
    // Global listeners survive moving the element into the body portal; pointer capture would not.
  };

  const reset = () => { drag.current = null; setDragging(false); setDragDirection(null); update(null); };
  const onHandleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Home") { event.preventDefault(); reset(); return; }
    const directions: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const direction = directions[event.key];
    if (!direction) return;
    event.preventDefault();
    const bounds = container.current?.getBoundingClientRect();
    if (!bounds) return;
    const step = event.shiftKey ? 40 : 10;
    moveTo(bounds.left + direction[0] * step, bounds.top + direction[1] * step);
    requestAnimationFrame(() => container.current?.querySelector<HTMLButtonElement>("[data-companion-drag-handle]")?.focus());
  };

  const style: CSSProperties | undefined = position ? {
    position: "fixed",
    left: EDGE + position.x * Math.max(0, geometry.viewportWidth - geometry.width - EDGE * 2),
    top: EDGE + position.y * Math.max(0, geometry.viewportHeight - geometry.height - EDGE * 2),
    margin: 0,
  } : undefined;

  return { setContainer, floating: position !== null, dragging, dragDirection, style, onPointerDown, onHandleKeyDown, reset };
}
