
import { useEffect, useState, useRef } from "react";
import {
  LineChart,
  CloudSun,
  Wind,
  TrendingUp,
  Brain,
  Menu,
} from "lucide-react";

const NAV_ITEMS = [
  { id: "trend", label: "24h Trend", icon: LineChart },
  { id: "conditions", label: "Weather Information", icon: CloudSun },
  { id: "pollutants", label: "Pollutant Information", icon: Wind },
  { id: "prediction", label: "Prediction Graph", icon: TrendingUp },
  { id: "shap", label: "SHAP Analysis", icon: Brain },
];

/* =========================================================
   FIND WHICH SECTION IS CURRENTLY AT THE TOP OF THE PAGE
   ========================================================= */

function getActiveSection() {
  const headerOffset = 120;
  let currentSection = NAV_ITEMS[0].id;

  for (const item of NAV_ITEMS) {
    const section = document.getElementById(item.id);

    if (!section) continue;

    const rect = section.getBoundingClientRect();

    if (rect.top <= headerOffset) {
      currentSection = item.id;
    }
  }

  return currentSection;
}

/* =========================================================
   SCROLL TRACKING
   ========================================================= */

function useActiveSection() {
  const [activeId, setActiveId] = useState(NAV_ITEMS[0].id);

  // Prevent scroll tracking from overriding the item
  // immediately after the user clicks it.
  const navigationLock = useRef(false);

  useEffect(() => {
    const handleScroll = () => {
      // If the user has just clicked a navigation item,
      // don't let the scroll event change the active item
      // while smooth scrolling is happening.
      if (navigationLock.current) {
        return;
      }

      const current = getActiveSection();

      setActiveId((previous) => {
        if (previous === current) {
          return previous;
        }

        return current;
      });
    };

    window.addEventListener("scroll", handleScroll, {
      passive: true,
    });

    // Set initial active section
    handleScroll();

    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  /*
   * Called when a navigation item is clicked.
   *
   * It immediately changes the blue highlight and then
   * locks the active state during smooth scrolling.
   */
  const navigateTo = (id) => {
    setActiveId(id);

    navigationLock.current = true;

    const element = document.getElementById(id);

    if (element) {
      element.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }

    /*
     * Wait until smooth scrolling has finished.
     * Then unlock normal scroll-based active detection.
     */
    setTimeout(() => {
      navigationLock.current = false;

      // Make absolutely sure the final section is correct.
      const finalSection = getActiveSection();

      setActiveId(finalSection);
    }, 800);
  };

  return {
    activeId,
    navigateTo,
  };
}

/* =========================================================
   DESKTOP SIDEBAR
   ========================================================= */

export default function Sidebar() {
  const { activeId, navigateTo } = useActiveSection();

  return (
    <aside
      className="
        hidden
        lg:flex
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
      {/* =================================================
          SIDEBAR HEADER
          ================================================= */}

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
        {/* Menu icon */}

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

        {/* Sections text */}

        <div
          className="
            absolute
            left-[108px]
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

      {/* =================================================
          DESKTOP NAVIGATION
          ================================================= */}

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
              onClick={() => navigateTo(id)}
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
                transition-all
                duration-200
                ${
                  active
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:text-ink hover:bg-canvas"
                }
              `}
            >
              {/* Icon */}

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
  );
}
