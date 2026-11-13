"use client";

import { Component, useEffect, useState, type ReactNode } from "react";
import { A2uiSurface, createComponentImplementation, type ReactCatalogComponent } from "@a2ui/react/v0_9";
import { Catalog, MessageProcessor, type SurfaceModel } from "@a2ui/web_core/v0_9";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chartProps, layoutProps, metricProps, parseSurface, tableProps, textProps, CATALOG_ID } from "@/lib/presentation";

function DataTable({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead><tr>{columns.map((column, index) => (
          <th key={index} scope="col" className="border-b border-border px-3 py-2 font-medium">{column}</th>
        ))}</tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr key={index}>{row.map((cell, column) => (
            <td key={column} className="border-b border-border px-3 py-2">{cell}</td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

const entries: ReactCatalogComponent[] = [
  ...(["Row", "Column"] as const).map(name => createComponentImplementation({ name, schema: layoutProps }, ({ props, buildChild }) => <div className={name === "Row" ? "flex min-w-0 flex-wrap gap-4" : "flex min-w-0 flex-col gap-4"}>{props.children.map(child => <div key={child} className="min-w-0 flex-1">{buildChild(child)}</div>)}</div>)),
  createComponentImplementation({ name: "Text", schema: textProps }, ({ props }) => <p className="whitespace-pre-wrap break-words">{props.text}</p>),
  createComponentImplementation({ name: "Metric", schema: metricProps }, ({ props }) => <dl className="rounded-lg border border-border p-4"><dt className="text-sm text-muted-foreground">{props.label}</dt><dd className="mt-1 break-words text-2xl font-semibold">{props.value}</dd></dl>),
  createComponentImplementation({ name: "Table", schema: tableProps }, ({ props }) => <DataTable {...props} />),
  ...(["BarChart", "LineChart"] as const).map(name => createComponentImplementation({ name, schema: chartProps }, ({ props }) => {
    const Chart = name === "BarChart" ? BarChart : LineChart;
    return <figure className="min-w-0"><figcaption className="mb-3 font-medium">{props.title} ({props.unit})</figcaption><div className="h-64 min-w-0 w-full"><ResponsiveContainer width="100%" height="100%"><Chart data={props.points} accessibilityLayer><XAxis dataKey="label" /><YAxis width={65} /><Tooltip />{name === "BarChart" ? <Bar dataKey="value" name={props.unit} fill="var(--primary)" isAnimationActive={false} /> : <Line dataKey="value" name={props.unit} stroke="var(--primary)" isAnimationActive={false} />}</Chart></ResponsiveContainer></div><details className="mt-2"><summary className="cursor-pointer text-sm text-muted-foreground">View chart data</summary><DataTable columns={["Label", props.unit]} rows={props.points.map(point => [point.label, point.value])} /></details></figure>;
  })),
];
const catalog = new Catalog<ReactCatalogComponent>(CATALOG_ID, "v0.9", entries, []);
const fallback = <p role="status" className="text-sm text-muted-foreground">This visual could not be displayed. Refer to the response text.</p>;

class VisualBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? fallback : this.props.children; }
}

function Surface({ value }: { value: unknown }) {
  const [state, setState] = useState<{ surface: SurfaceModel<ReactCatalogComponent>; title: string; source: string; incomplete: boolean } | null>(null);
  useEffect(() => {
    const parsed = parseSurface(value);
    if (!parsed) return;
    const processor = new MessageProcessor<ReactCatalogComponent>([catalog]);
    let active = true;
    // Publish only a fully processed surface; Strict Mode cleanup cancels stale work.
    queueMicrotask(() => {
      if (!active) return;
      try {
        processor.processMessages(parsed.messages);
        const surface = processor.getSurface(parsed.id);
        if (surface) setState({ surface, title: parsed.title, source: parsed.source, incomplete: parsed.incomplete });
      } catch { setState(null); }
    });
    return () => { active = false; processor.dispose(); };
  }, [value]);
  if (!state) return fallback;
  return (
    <section aria-label={state.title} className="my-4 min-w-0 break-words rounded-xl border border-border bg-card p-4">
      <h3 className="mb-1 font-semibold">{state.title}</h3>
      <p className="mb-4 text-xs text-muted-foreground">Source: {state.source}{state.incomplete ? " · Incomplete results" : ""}</p>
      <A2uiSurface surface={state.surface} />
    </section>
  );
}

export default function Presentation({ surfaces }: { surfaces: unknown[] }) {
  if (!Array.isArray(surfaces) || surfaces.length > 4) return fallback;
  return surfaces.map((value, index) => <VisualBoundary key={`${index}:${JSON.stringify(value)}`}><Surface value={value} /></VisualBoundary>);
}
