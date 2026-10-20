# Svaar web

Next.js client site for Svaar. Independent of the Python service.

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
npm run build      # production build
npm run typecheck
```

- Font: Gotu, loaded with `next/font/google`.
- Assets in `public/`: `background.gif` (animated background), `background-still.jpg`
  (first frame, shown when the visitor prefers reduced motion) and `swan.png`
  (logo with a transparent background).
- Contact links in `app/page.tsx` are placeholders (`#`) until real destinations are set.
