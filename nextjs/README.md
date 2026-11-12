This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

The default development and production build scripts use Webpack (`next dev --webpack` and `next build --webpack`).

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Stylesheet verification

Tailwind v4 runs through `postcss.config.mjs` for both Webpack and Turbopack.
Keep `@tailwindcss/postcss` aligned with the installed Tailwind version; a
Turbopack-only loader leaves Webpack pages without generated utilities.

With the development server running, run `npm run check:styles`. This checks
that the page serves compiled CSS containing layout, color, and screen-reader
utilities. Pass another server URL with `npm run check:styles -- http://localhost:3000`.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## Regression checks

Run `npm test` for split-event, conversation-ID, malformed-event, and interrupted-stream checks. Run `npm run lint` and `npx tsc --noEmit` before review.

## Tool registry

Open the sidebar’s Tool registry to save, edit, test, remove, and explicitly enable MCP or GET API tools. API test inputs are generated from the scalar query schema. Saving is distinct from testing and activation. `npm test` includes schema and argument regression checks.

## Local specialist demo

The chat starters exercise PayPal invoice drafts, paginated completed sales totals by currency, and knowledge retrieval with system status. PayPal actions use local fictional data; approving a send records it locally and sends no email or payment. The approval card identifies local-only actions, and pending approvals and tool traces can be restored by reopening a conversation.

Tool traces show discovery, execution, approval decisions, and the catalog version when supplied by the backend. The backend still needs its configured model and embedding credentials for live chat; the frontend does not supply provider credentials.
