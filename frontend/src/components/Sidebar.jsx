import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LineChart,
  CloudSun,
  Wind,
  TrendingUp,
  Brain,
  Menu,
  X,
} from "lucide-react";

const NAV_ITEMS = [
  { id: "trend", label: "24h Trend", icon: LineChart },
  { id: "conditions", label: "Weather Information", icon: CloudSun },
  { id: "pollutants", label: "Pollutant Information", icon: Wind },
  { id: "prediction", label: "Prediction Graph", icon: TrendingUp },
  { id: "shap", label: "SHAP Analysis", icon: Brain },
];

/*
 * Tracks which section is currently visible.
 */
function useActiveSection(ids) {
  const [activeId, setActiveId] = useState(ids[0]);

  useEffect(() => {
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter(Boolean);

    if (!elements.length) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (a, b) =>
              a.boundingClientRect.top - b.boundingClientRect.top
          );

        if (visible.length > 0) {
          setActiveId(visible[0].target.id);
        }
      },
      {
        rootMargin: "-100px 0px -70% 0px",
        threshold: 0,
      }
    );

    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [ids]);

  return activeId;
}

function scrollToSection(id) {
  document
    .getElementById(id)
    ?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
}

/*
 * Mobile navigation
 */
function NavList({ activeId, onNavigate }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
        const active = activeId === id;

        return (
          <button
            key={id}
            onClick={() => {
              scrollToSection(id);
              onNavigate?.();
            }}
            className={`
              flex items-center gap-3
              w-full
              px-3 py-3
              rounded-xl
              text-sm
              font-medium
              text-left
              transition-colors
              ${
                active
                  ? "bg-accent/10 text-accent"
                  : "text-muted hover:text-ink hover:bg-canvas"
              }
            `}
          >
            <Icon
              size={18}
              strokeWidth={2.25}
              className="shrink-0"
            />

            <span>{label}</span>
          </button>
        );
      })}
    </nav>
  );
}

export default function Sidebar() {
  const ids = NAV_ITEMS.map((item) => item.id);
  const activeId = useActiveSection(ids);

  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* =========================================================
          DESKTOP SIDEBAR
          ========================================================= */}

      <aside
        className="
          hidden lg:flex
          fixed
          left-0
          top-0
          bottom-0
          z-50
          group
          flex-col
          w-[74px]
          hover:w-[240px]
          bg-surface
          border-r
          border-border
          overflow-hidden
          transition-[width]
          duration-200
          ease-out
        "
      >
        {/* ---------------------------------------------------------
            TOP AREA
            --------------------------------------------------------- */}

        <div
          className="
            h-[64px]
            min-h-[64px]
            flex
            items-center
            border-b
            border-border
          "
        >
          {/* Menu / Close icon */}

          <div
            className="
              w-[74px]
              min-w-[74px]
              h-full
              flex
              items-center
              justify-center
              text-muted
            "
          >
            <Menu
              size={20}
              strokeWidth={2}
            />
          </div>

          {/* Title - appears only when expanded */}

          <div
            className="
              absolute
              left-[74px]
              flex
              items-center
              whitespace-nowrap
              opacity-0
              group-hover:opacity-100
              transition-opacity
              duration-150
            "
          >
            <span className="text-sm font-semibold text-ink">
              Sections
            </span>
          </div>
        </div>

        {/* ---------------------------------------------------------
            NAVIGATION
            --------------------------------------------------------- */}

        <nav
          className="
            flex
            flex-col
            gap-2
            pt-5
            px-2
          "
        >
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
            const active = activeId === id;

            return (
              <button
                key={id}
                onClick={() => scrollToSection(id)}
                title={label}
                className={`
                  relative
                  flex
                  items-center
                  h-[48px]
                  w-full
                  rounded-lg
                  text-sm
                  font-medium
                  whitespace-nowrap
                  transition-colors
                  ${
                    active
                      ? "bg-accent/10 text-accent"
                      : "text-muted hover:text-ink hover:bg-canvas"
                  }
                `}
              >
                {/* Icon container */}

                <span
                  className="
                    w-[58px]
                    min-w-[58px]
                    flex
                    items-center
                    justify-center
                  "
                >
                  <Icon
                    size={21}
                    strokeWidth={2.1}
                    className="shrink-0"
                  />
                </span>

                {/* Label */}

                <span
                  className="
                    opacity-0
                    group-hover:opacity-100
                    transition-opacity
                    duration-150
                    ml-1
                  "
                >
                  {label}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      {/* =========================================================
          MOBILE MENU
          ========================================================= */}

      <motion.button
        onClick={() => setMobileOpen(true)}
        whileTap={{ scale: 0.95 }}
        className="
          lg:hidden
          fixed
          bottom-5
          right-5
          z-40
          w-12
          h-12
          rounded-full
          bg-accent
          text-white
          shadow-lg
          flex
          items-center
          justify-center
        "
        aria-label="Open section navigation"
      >
        <Menu
          size={20}
          strokeWidth={2.25}
        />
      </motion.button>

      <AnimatePresence>
        {mobileOpen && (
          <>
            {/* Overlay */}

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
              className="
                lg:hidden
                fixed
                inset-0
                bg-black/50
                z-40
              "
            />

            {/* Mobile drawer */}

            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{
                type: "tween",
                duration: 0.25,
              }}
              className="
                lg:hidden
                fixed
                top-0
                right-0
                bottom-0
                w-72
                max-w-[80%]
                bg-surface
                border-l
                border-border
                z-50
                p-4
                shadow-2xl
              "
            >
              <div
                className="
                  flex
                  items-center
                  justify-between
                  mb-4
                "
              >
                <p className="text-sm font-semibold text-ink">
                  Sections
                </p>

                <button
                  onClick={() => setMobileOpen(false)}
                  className="
                    w-8
                    h-8
                    rounded-full
                    flex
                    items-center
                    justify-center
                    text-muted
                    hover:text-ink
                    hover:bg-canvas
                    transition-colors
                  "
                  aria-label="Close"
                >
                  <X
                    size={16}
                    strokeWidth={2.25}
                  />
                </button>
              </div>

              <NavList
                activeId={activeId}
                onNavigate={() => setMobileOpen(false)}
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}