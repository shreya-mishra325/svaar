"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./intro.module.css";
import { crestAt, createWater, type Water } from "./water";

// Timeline in milliseconds. One scroll starts it and it always plays through:
// the wave rises carrying the landing page, clears the logo screen, crashes into
// the top edge, then the water leaves through the top and the page stays.
const RISE_MS = 1300;
const CRASH_MS = 550;
const EXIT_MS = 950;
const TOTAL_MS = RISE_MS + CRASH_MS + EXIT_MS;
const CREST_POINTS = 48;

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);

type Phase = "intro" | "playing" | "done";

type Props = {
  /** The big logo screen. */
  children: React.ReactNode;
  /** A decorative copy of the landing hero, carried in on the wave. */
  carried: React.ReactNode;
};

/** Full-screen intro that plays a water transition into the landing page on first scroll. */
export default function Intro({ children, carried }: Props) {
  const [phase, setPhase] = useState<Phase>("intro");
  const overlay = useRef<HTMLDivElement>(null);
  const cover = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const carryClip = useRef<HTMLDivElement>(null);
  const carryPage = useRef<HTMLDivElement>(null);
  const ripple = useRef<SVGFEDisplacementMapElement>(null);

  // Block scrolling of the page underneath until the intro has finished.
  useEffect(() => {
    if (phase === "done") return;
    const root = document.documentElement;
    root.style.overflow = "hidden";
    const block = (e: Event) => e.preventDefault();
    window.addEventListener("touchmove", block, { passive: false });
    window.addEventListener("wheel", block, { passive: false });
    return () => {
      window.removeEventListener("touchmove", block);
      window.removeEventListener("wheel", block);
    };
  }, [phase]);

  // Any scroll intent starts the animation.
  useEffect(() => {
    if (phase !== "intro") return;
    document.documentElement.dataset.intro = "intro";
    window.scrollTo(0, 0);

    let touchY = 0;
    const play = () => setPhase("playing");
    const onWheel = (e: WheelEvent) => e.deltaY > 0 && play();
    const onTouchStart = (e: TouchEvent) => {
      touchY = e.touches[0]?.clientY ?? 0;
    };
    const onTouchMove = (e: TouchEvent) => {
      if (touchY - (e.touches[0]?.clientY ?? touchY) > 12) play();
    };
    const onKey = (e: KeyboardEvent) => {
      if (["ArrowDown", "PageDown", " ", "Enter"].includes(e.key)) play();
    };
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKey);
    };
  }, [phase]);

  useEffect(() => {
    if (phase !== "playing") return;
    const root = document.documentElement;
    const overlayEl = overlay.current;
    const coverEl = cover.current;
    const canvasEl = canvas.current;
    const clipEl = carryClip.current;
    const pageEl = carryPage.current;
    const rippleEl = ripple.current;
    if (!overlayEl || !coverEl || !canvasEl || !clipEl || !pageEl || !rippleEl) return;

    // The intro unmounts for good: scrolling back up only reaches the landing page.
    const finish = () => {
      root.dataset.intro = "done";
      root.style.overflow = "";
      window.scrollTo(0, 0);
      setPhase("done");
    };

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const water: Water | null = reduced ? null : createWater(canvasEl, "/background-still.jpg");
    if (!water) {
      root.dataset.intro = "reveal";
      overlayEl.classList.add(styles.fading);
      const timer = window.setTimeout(finish, 700);
      return () => window.clearTimeout(timer);
    }

    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = now - start;
      const seconds = t / 1000;
      const rise = ease(clamp01(t / RISE_MS));
      const impact = clamp01((t - RISE_MS) / CRASH_MS);
      const exit = ease(clamp01((t - RISE_MS - CRASH_MS) / EXIT_MS));
      // Crest reaches the top edge, then surges past it on impact.
      const front = -0.15 + 1.15 * rise + 0.45 * (1 - (1 - impact) ** 3);
      const back = -0.6 + 2.0 * exit;
      const crash = t > RISE_MS ? Math.sin(Math.PI * impact) * (1 - 0.4 * impact) : 0;

      // The carried page rides with its top at the crest and lands at the top edge.
      const landed = Math.min(front, 1);
      pageEl.style.transform = `translateY(${(1 - landed) * 100}vh)`;
      const aspect = window.innerWidth / window.innerHeight;
      const points = [];
      for (let i = 0; i <= CREST_POINTS; i += 1) {
        const x = i / CREST_POINTS;
        const y = (1 - crestAt(x, aspect, seconds, front, crash)) * 100;
        points.push(`${(x * 100).toFixed(2)}% ${Math.max(y, -5).toFixed(2)}%`);
      }
      clipEl.style.clipPath = `polygon(${points.join(", ")}, 100% 100%, 0% 100%)`;
      // Underwater ripple distortion that settles as the water leaves.
      const settle = clamp01((t - RISE_MS) / (CRASH_MS + EXIT_MS * 0.8));
      rippleEl.setAttribute("scale", String(26 * (1 - settle) + 14 * crash));

      // Clear the logo screen once the crash has fully covered it.
      if (front > 1.18 && coverEl.style.visibility !== "hidden") {
        coverEl.style.visibility = "hidden";
        root.dataset.intro = "reveal";
      }
      water.render(seconds, { front, back, crash });
      if (t < TOTAL_MS) {
        frame = requestAnimationFrame(tick);
      } else {
        finish();
      }
    };
    frame = requestAnimationFrame(tick);
    const onResize = () => water.resize();
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      water.dispose();
    };
  }, [phase]);

  if (phase === "done") return null;

  return (
    <div
      ref={overlay}
      className={styles.overlay}
      onClick={() => setPhase((p) => (p === "intro" ? "playing" : p))}
    >
      <svg className={styles.defs} aria-hidden="true">
        <filter id="carry-ripple" x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.008 0.018" numOctaves="2" seed="7">
            <animate attributeName="seed" values="7;9;11;7" dur="0.9s" repeatCount="indefinite" />
          </feTurbulence>
          <feDisplacementMap ref={ripple} in="SourceGraphic" scale="26" xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
      <div ref={cover} className={styles.cover}>
        <img className={styles.background} src="/background.gif" alt="" aria-hidden="true" />
        {children}
      </div>
      <canvas ref={canvas} className={styles.water} aria-hidden="true" />
      <div ref={carryClip} className={styles.carry} inert>
        <div ref={carryPage} className={styles.carryPage}>
          {carried}
        </div>
      </div>
    </div>
  );
}
