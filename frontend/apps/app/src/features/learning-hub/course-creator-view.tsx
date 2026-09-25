import { Button } from "@v1/ui/button";
import { Input } from "@v1/ui/input";
import { Sparkles } from "lucide-react";

import { STUDY_PLAN_FORM } from "./demo-data";
import { SoonLabel, ToolPage } from "./tool-page";

const selectClass =
  "focus-field h-11 w-full rounded-xl border border-input bg-surface px-3 text-base font-medium text-foreground focus-visible:bg-card sm:h-10 sm:text-sm";

/** Course Creator (preview): the study-plan form; generating a plan is not built yet. */
export function CourseCreatorView() {
  return (
    <ToolPage width="narrow">
      <section className="space-y-6 rounded-2xl border border-border bg-card p-5 elev-1 sm:p-6">
        <div className="text-center">
          <span
            aria-hidden
            className="mx-auto mb-2 grid h-12 w-12 place-items-center rounded-xl bg-accent-purple-soft text-accent-purple"
          >
            <Sparkles className="h-6 w-6" />
          </span>
          <h2 className="text-xl font-bold text-foreground">AI Custom Study Plan Generator</h2>
          <p className="mt-1 text-xs text-text-secondary">
            Create a tailored study schedule for your upcoming Board Exams or Term Tests.
          </p>
        </div>

        <form className="space-y-4" onSubmit={(event) => event.preventDefault()}>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="plan-goal" className="text-xs font-bold text-foreground">
              Target Exam / Goal
            </label>
            <Input id="plan-goal" defaultValue={STUDY_PLAN_FORM.goal} />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="plan-board" className="text-xs font-bold text-foreground">
                Board
              </label>
              <select id="plan-board" className={selectClass} defaultValue={STUDY_PLAN_FORM.boards[0]}>
                {STUDY_PLAN_FORM.boards.map((board) => (
                  <option key={board}>{board}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="plan-hours" className="text-xs font-bold text-foreground">
                Study Hours / Day
              </label>
              <select id="plan-hours" className={selectClass} defaultValue={STUDY_PLAN_FORM.hours[0]}>
                {STUDY_PLAN_FORM.hours.map((hours) => (
                  <option key={hours}>{hours}</option>
                ))}
              </select>
            </div>
          </div>
          <Button
            type="submit"
            disabled
            className="w-full bg-accent-purple text-accent-purple-foreground shadow-accent-purple/20 hover:bg-accent-purple"
          >
            <SoonLabel>Generate Personalized Roadmap</SoonLabel>
          </Button>
        </form>
      </section>
    </ToolPage>
  );
}
