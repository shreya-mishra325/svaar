import Image from "next/image";
import type { IconType } from "react-icons";
import { BsGridFill } from "react-icons/bs";
import {
  FaDiscord,
  FaEnvelope,
  FaPhoneAlt,
  FaRegUserCircle,
  FaSlack,
  FaTelegramPlane,
} from "react-icons/fa";
import styles from "./page.module.css";
import Intro from "./intro";

// Placeholder destinations until the team supplies real contact links.
const contacts: { label: string; href: string; icon: IconType }[] = [
  { label: "Email", href: "#", icon: FaEnvelope },
  { label: "Phone", href: "#", icon: FaPhoneAlt },
  { label: "Discord", href: "#", icon: FaDiscord },
  { label: "Slack", href: "#", icon: FaSlack },
  { label: "Telegram", href: "#", icon: FaTelegramPlane },
];

const features = [
  {
    title: "Ask What Happened. Hear the Timeline.",
    body: "When a pipeline breaks, ask Svaar in chat or on a call. It rebuilds the incident from recorded events, in order, with the source of every step, and names the step that failed. No digging through logs.",
  },
  {
    title: "Claims, Checked Against Evidence.",
    body: "Someone says the fix is merged. Svaar looks for the merge. If the evidence is there, the claim is confirmed. If it is not, Svaar calls that person and asks. A missed call or a busy line never counts against anyone.",
  },
  {
    title: "It Calls When Nobody Answers.",
    body: "Svaar alerts the owner in team chat the moment CI fails. If nobody acknowledges in time, it phones them, explains what broke in two plain sentences, and lets them acknowledge right there on the call.",
  },
];

const cards = [
  {
    title: "One Agent, Chat and Voice.",
    body: "Team chat and phone calls reach the same agent, the same tools and the same rules. Pick up wherever you are.",
  },
  {
    title: "Verified, Every Time.",
    body: "People join with single-use invites, and phones are verified by a code read aloud on a call. Nobody gets in by claiming to be someone.",
  },
  {
    title: "Risky Actions Wait for You.",
    body: "Reruns and other risky actions need a one-time code from the owner on a second channel. They run once, and only once.",
  },
  {
    title: "Plans That Pass the Validator.",
    body: "Release freezes, on-call coverage and deploy slots are negotiated into a plan, and only a plan that passes every hard rule is accepted.",
  },
  {
    title: "Replay Without Risk.",
    body: "Try the corrected pipeline in a sandbox first. Results are clearly marked as simulated and never touch production.",
  },
  {
    title: "Every Decision on Record.",
    body: "Each decision and each action is written down with its reason, so you can always see what Svaar did and why.",
  },
];

function ContactLinks() {
  return (
    <nav className={styles.contacts} aria-label="Contact">
      {contacts.map(({ label, href, icon: Icon }) => (
        <a key={label} href={href} aria-label={label} className={styles.contact}>
          <Icon />
        </a>
      ))}
    </nav>
  );
}

/** Landing hero. The decorative copy is the one the intro wave carries in. */
function Hero({ decorative = false }: { decorative?: boolean }) {
  const Brand = decorative ? "div" : "h1";
  return (
    <section className={styles.hero} aria-hidden={decorative || undefined}>
      <header className={styles.header}>
        <button
          type="button"
          className={styles.iconButton}
          aria-label="Open menu"
          tabIndex={decorative ? -1 : undefined}
        >
          <BsGridFill />
        </button>

        <Brand className={styles.brand}>
          <Image src="/swan.png" alt="" width={894} height={868} className={styles.swan} />
          <span className={styles.wordmark}>vaar</span>
          <span className={styles.visuallyHidden}>Svaar</span>
        </Brand>

        <button
          type="button"
          className={styles.iconButton}
          aria-label="Account"
          tabIndex={decorative ? -1 : undefined}
        >
          <FaRegUserCircle />
        </button>
      </header>

      <div className={styles.intro}>
        <p>
          Svaar is a voice-enabled agent for engineering incidents. It lives in team chat,
          watches CI, rebuilds what happened from recorded events, checks status claims against
          evidence, calls engineers by phone to verify them, and negotiates conflicting
          constraints into a plan that deterministic code has validated.
        </p>
      </div>
    </section>
  );
}

export default function Home() {
  return (
    <main className={styles.page}>
      <picture className={styles.background} aria-hidden="true">
        <source srcSet="/background-still.jpg" media="(prefers-reduced-motion: reduce)" />
        <img src="/background.gif" alt="" />
      </picture>

      <Intro carried={<Hero decorative />}>
        <div className={styles.splash}>
          <div className={styles.splashBrand}>
            <Image
              src="/swan.png"
              alt=""
              width={894}
              height={868}
              priority
              className={styles.splashSwan}
            />
            <span className={styles.splashWordmark}>vaar</span>
            <span className={styles.visuallyHidden}>Svaar</span>
          </div>
          <span className={styles.scrollHint} aria-hidden="true" />
        </div>
      </Intro>

      <Hero />

      <section id="features" className={styles.features} aria-label="What Svaar does">
        {features.map((feature) => (
          <article key={feature.title} className={styles.feature}>
            <h3>{feature.title}</h3>
            <p>{feature.body}</p>
          </article>
        ))}
      </section>

      <section id="safety" className={styles.cards} aria-label="How Svaar keeps you safe">
        {cards.map((card) => (
          <article key={card.title} className={styles.card}>
            <h4>{card.title}</h4>
            <p>{card.body}</p>
          </article>
        ))}
      </section>

      <section id="contact" className={styles.closing}>
        <ContactLinks />
      </section>

      <footer className={styles.footer}>
        <p>Models propose, deterministic code enforces, Bolna speaks.</p>
      </footer>
    </main>
  );
}
