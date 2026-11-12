"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Wrench } from "lucide-react";
import GlideMenu from "@/components/primitives/GlideMenu";

export type SidebarRecent = {
  id: string;
  label: string;
};

type SidebarNavProps = {
  activeId?: string | null;
  className?: string;
  fill?: boolean;
  onNewChat?: () => void;
  onPick?: (id: string, label: string) => void;
  recents: SidebarRecent[];
  workspaceName?: string;
  disabled?: boolean;
  onCollapse?: () => void;
  onToolRegistry?: () => void;
};

const SIDEBAR_MOTION = {
  expandedWidth: 224,
  collapsedWidth: 52,
  copyDuration: 180,
  copyOffset: 8,
  easing: "cubic-bezier(0.22, 1, 0.36, 1)",
};

const CHAT_SEARCH_MOTION = {
  duration: 180,
  easing: "cubic-bezier(0.22, 1, 0.36, 1)",
};

function GlideGroup({ children }: { children: ReactNode }) {
  return (
    <GlideMenu
      rowSelector="[data-row]"
      highlightClassName="sidebar-glide-highlight rounded-[7px] bg-hover-2"
      className="group/glide flex flex-col gap-1"
    >
      {children}
    </GlideMenu>
  );
}

function RailButton({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      data-row
      type="button"
      onClick={onClick}
      className="sidebar-row relative z-10 mx-2 flex h-8 items-center rounded-[8px] px-2 text-left transition-[background-color,color,transform] duration-150 active:scale-[0.98]"
    >
      <span className="flex size-5 shrink-0 items-center justify-center text-ink-2">
        {icon}
      </span>
      <span className="sidebar-copy ml-2 min-w-0 flex-1 truncate text-[14px] font-medium text-ink-2">
        {label}
      </span>
    </button>
  );
}

export default function SidebarNav({
  activeId,
  className = "",
  fill = false,
  onNewChat,
  onPick,
  recents,
  workspaceName = "Agent workspace",
  disabled = false,
  onCollapse,
  onToolRegistry,
}: SidebarNavProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const visibleRecents = recents.filter((item) => item.label.toLowerCase().includes(query.trim().toLowerCase()));

  useEffect(() => {
    if (searchOpen) searchRef.current?.focus();
  }, [searchOpen]);

  const collapse = () => {
    if (onCollapse) { onCollapse(); return; }
    setCollapsed(true);
    setSearchOpen(false);
    setQuery("");
  };

  return (
    <aside
      data-sidebar-collapsed={collapsed}
      aria-label="Workspace navigation"
      className={`relative flex shrink-0 overflow-hidden ${fill ? "h-full" : "h-[600px]"} ${className}`}
      style={{
        width: collapsed ? SIDEBAR_MOTION.collapsedWidth : SIDEBAR_MOTION.expandedWidth,
        transitionTimingFunction: SIDEBAR_MOTION.easing,
        "--sidebar-copy-duration": `${SIDEBAR_MOTION.copyDuration}ms`,
        "--sidebar-copy-offset": `${SIDEBAR_MOTION.copyOffset}px`,
        "--sidebar-easing": SIDEBAR_MOTION.easing,
      } as CSSProperties}
    >
      <div className="flex min-h-0 w-[224px] shrink-0 flex-col">
        <div className="relative mb-3 h-10 shrink-0">
          <div aria-hidden={collapsed} className="absolute left-2 top-1 flex h-8 w-[164px] items-center rounded-[8px] px-2">
            <span className="sidebar-logo flex size-5 shrink-0 items-center justify-center text-ink">
              <IconPopsicle2 size={18} />
            </span>
            <span className="sidebar-copy ml-2 min-w-0 flex-1 truncate text-[14px] font-medium text-ink-2">
              {workspaceName}
            </span>
          </div>

          <button
            type="button"
            aria-label={onCollapse ? "Close navigation" : "Collapse sidebar"}
            aria-hidden={collapsed}
            tabIndex={collapsed ? -1 : 0}
            onClick={collapse}
            className="sidebar-collapse-control absolute right-2 top-1 flex size-8 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <IconSidebarLeftArrow size={18} />
          </button>
          <button
            type="button"
            aria-label="Expand sidebar"
            aria-hidden={!collapsed}
            tabIndex={collapsed ? 0 : -1}
            onClick={() => setCollapsed(false)}
            className="sidebar-expand-control absolute left-2 top-0.5 flex size-9 items-center justify-center rounded-[8px] text-ink-3 rotate-180 transition-[opacity,background-color,color] duration-150 hover:bg-hover-2 hover:text-ink"
          >
            <IconSidebarLeftArrow size={18} />
          </button>
        </div>

        <GlideGroup>
          <RailButton
            icon={<IconEditBig size={18} />}
            label="New chat"
            onClick={() => { if (!disabled) onNewChat?.(); }}
          />
          <RailButton icon={<Wrench size={18} />} label="Tool registry" onClick={onToolRegistry} />
        </GlideGroup>

        <div className="mt-6 min-h-0 flex-1 overflow-y-auto">
          <div className="sidebar-copy relative mx-2 mb-1 h-8">
            <div
              aria-hidden={searchOpen}
              className={`absolute inset-0 flex items-center gap-2 px-2 text-xs font-medium text-ink-3 transition-[opacity,transform] ${searchOpen ? "pointer-events-none -translate-x-1 opacity-0" : "translate-x-0 opacity-100"}`}
              style={{ transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`, transitionTimingFunction: CHAT_SEARCH_MOTION.easing }}
            >
              <IconChevronDownSmall size={16} />
              <span>Chats</span>
            </div>

            <button
              type="button"
              aria-label="Search chats"
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen(true)}
              className={`absolute right-0 top-0 z-10 flex size-8 items-center justify-center rounded-[8px] text-ink-3 transition-[opacity,background-color,color,transform] hover:bg-hover-2 hover:text-ink active:scale-[0.96] ${searchOpen ? "pointer-events-none opacity-0" : "opacity-100"}`}
              style={{ transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms` }}
            >
              <IconMagnifyingGlass size={16} />
            </button>

            <div
              inert={!searchOpen}
              className={`absolute right-0 top-0 z-20 flex h-8 w-full items-center overflow-hidden rounded-[8px] bg-field text-ink-3 shadow-hairline transition-opacity focus-within:text-ink-2 ${searchOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"}`}
              style={{
                transitionDuration: `${CHAT_SEARCH_MOTION.duration}ms`,
                transitionTimingFunction: CHAT_SEARCH_MOTION.easing,
              }}
            >
              <span className="ml-2 flex shrink-0 items-center justify-center">
                <IconMagnifyingGlass size={15} />
              </span>
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setSearchOpen(false);
                    setQuery("");
                  }
                }}
                placeholder="Search chats"
                aria-label="Search chat history"
                className="ml-2 min-w-0 flex-1 bg-transparent text-sm font-medium text-ink outline-none placeholder:text-ink-3"
              />
              <button
                type="button"
                aria-label="Close chat search"
                onClick={() => {
                  setSearchOpen(false);
                  setQuery("");
                }}
                className="flex size-8 shrink-0 items-center justify-center rounded-[8px] text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover-2 hover:text-ink active:scale-[0.96]"
              >
                <IconCrossSmall size={16} />
              </button>
            </div>
          </div>

          <GlideGroup>
            {visibleRecents.map((item) => {
              const active = item.id === activeId;
              return (
                <button
                  key={item.id}
                  data-row
                  type="button"
                  title={item.label}
                  disabled={disabled}
                  onClick={() => {
                    onPick?.(item.id, item.label);
                  }}
                  className={`sidebar-row relative z-10 mx-2 flex h-8 items-center rounded-[8px] px-2 text-left transition-[background-color,color,transform] duration-150 active:scale-[0.98] ${
                    active ? "bg-hover-2 group-hover/glide:bg-transparent" : ""
                  }`}
                >
                  <span className={`sidebar-copy min-w-0 flex-1 truncate text-[14px] font-medium ${active ? "text-ink" : "text-ink-2"}`}>
                    {item.label}
                  </span>
                </button>
              );
            })}
            {query && visibleRecents.length === 0 && (
              <div className="sidebar-copy mx-2 px-2 py-2 text-xs text-ink-3">No chats found</div>
            )}
          </GlideGroup>
          {!recents.length && <p className="sidebar-copy px-4 py-2 text-xs leading-5 text-muted-foreground">Your conversations will appear here</p>}
        </div>

        <div className="mx-2 mt-4 w-[208px] border-t border-line pt-4" role="group" aria-label="User profile">
          <div className="flex h-10 items-center gap-3 px-2">
            <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-field text-xs font-medium text-ink">Y</span>
            <div className="sidebar-copy min-w-0">
              <p className="truncate text-sm font-medium text-ink">You</p>
              <p className="text-xs text-muted-foreground">Local profile</p>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ─────────────────────────────────────────────────────────
 * INLINE SVG ICONS (matching PromptBar style)
 * ───────────────────────────────────────────────────────── */

function Icon({ children, size = 15, strokeWidth = 1.8 }: { children: React.ReactNode; size?: number; strokeWidth?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}



function IconChevronDownSmall({ size = 16 }: { size?: number }) {
  return <Icon size={size} strokeWidth={2.4}><path d="M6 9l6 6 6-6" /></Icon>;
}

function IconCrossSmall({ size = 16 }: { size?: number }) {
  return <Icon size={size} strokeWidth={2.5}><path d="M18 6L6 18M6 6l12 12" /></Icon>;
}

function IconEditBig({ size = 18 }: { size?: number }) {
  return <Icon size={size} strokeWidth={1.8}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></Icon>;
}


function IconMagnifyingGlass({ size = 16 }: { size?: number }) {
  return <Icon size={size} strokeWidth={2}><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></Icon>;
}


function IconPopsicle2({ size = 18 }: { size?: number }) {
  return (
    <Icon size={size} strokeWidth={1.8}>
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2z" />
      <path d="M12 6v6l4 4" />
    </Icon>
  );
}


function IconSidebarLeftArrow({ size = 18 }: { size?: number }) {
  return <Icon size={size}><path d="M19 12H5" /><path d="M12 19l-7-7 7-7" /></Icon>;
}
