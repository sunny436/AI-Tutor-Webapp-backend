import { createContext } from "react";

import type { Citation } from "@/lib/api/types";

/**
 * True only for the last block of a reply that is still streaming. Widgets that need their
 * whole source (a diagram, a chart, a quiz) wait for it instead of drawing half of it.
 */
export const LiveContext = createContext(false);

/**
 * What the reply's [1] and [F1] markers point at. `undefined` = not known yet (the reply is
 * still streaming, or it came from before citations existed): never "missing".
 */
export const CitationsContext = createContext<Citation[] | undefined>(undefined);
