import { z } from "zod";

export const CATALOG_ID = "urn:agent-tool-scale:read-only:v1";
const text = z.string().max(2000).regex(/^[^<>]*$/).refine(value => !/(?:https?:|javascript:|data:|file:|ftp:|www\.|\/\/)/i.test(value));
const id = z.string().regex(/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/);
export const layoutProps = z.object({
  children: z.array(id.describe("REF:common_types.json#/$defs/ComponentId")).min(1).max(49).describe("REF:common_types.json#/$defs/ChildList"),
}).strict();
export const textProps = z.object({ text }).strict();
export const metricProps = z.object({ label: text, value: text }).strict();
export const tableProps = z.object({ columns: z.array(text).min(1).max(12), rows: z.array(z.array(z.union([text, z.number().finite()]))).max(200) }).strict();
export const chartProps = z.object({ title: text, unit: text, points: z.array(z.object({ label: text, value: z.number().finite() }).strict()).min(1).max(200) }).strict();
const component = z.discriminatedUnion("component", [
  layoutProps.extend({ id, component: z.literal("Row") }),
  layoutProps.extend({ id, component: z.literal("Column") }),
  textProps.extend({ id, component: z.literal("Text") }),
  metricProps.extend({ id, component: z.literal("Metric") }),
  tableProps.extend({ id, component: z.literal("Table") }),
  chartProps.extend({ id, component: z.literal("BarChart") }),
  chartProps.extend({ id, component: z.literal("LineChart") }),
]);
const surfaceSchema = z.object({
  id: z.string().min(1).max(200), title: text, source: text, incomplete: z.boolean(),
  messages: z.tuple([
    z.object({ version: z.literal("v0.9"), createSurface: z.object({ surfaceId: z.string(), catalogId: z.literal(CATALOG_ID) }).strict() }).strict(),
    z.object({ version: z.literal("v0.9"), updateComponents: z.object({ surfaceId: z.string(), components: z.array(component).min(1).max(50) }).strict() }).strict(),
  ]),
}).strict().superRefine((surface, context) => {
  const fail = () => context.addIssue({ code: z.ZodIssueCode.custom, message: "Invalid presentation tree" });
  if (new TextEncoder().encode(JSON.stringify(surface)).length > 128_000) fail();
  if (surface.messages.some(message => ("createSurface" in message ? message.createSurface : message.updateComponents).surfaceId !== surface.id)) fail();
  const nodes = surface.messages[1].updateComponents.components;
  const map = new Map(nodes.map(node => [node.id, node]));
  const seen = new Set<string>();
  function visit(key: string): void {
    const node = map.get(key);
    if (!node || seen.has(key)) { fail(); return; }
    seen.add(key);
    if ("children" in node) node.children.forEach(visit);
    if (node.component === "Table" && node.rows.some(row => row.length !== node.columns.length)) fail();
  }
  visit("root");
  if (map.size !== nodes.length || seen.size !== nodes.length) fail();
});

export type UISurface = z.infer<typeof surfaceSchema>;
export function parseSurface(value: unknown): UISurface | null {
  const result = surfaceSchema.safeParse(value);
  return result.success ? result.data : null;
}
