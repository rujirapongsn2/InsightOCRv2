import { Check } from "lucide-react"
import { WizardStep } from "@/types/schema"
import { cn } from "@/lib/utils"

interface Step {
  number: WizardStep
  title: string
  description?: string
}

interface StepperProps {
  steps: Step[]
  currentStep: WizardStep
  completedSteps?: WizardStep[]
}

export function Stepper({ steps, currentStep, completedSteps = [] }: StepperProps) {
  return (
    <nav aria-label="Progress">
      <ol className="flex items-center justify-between">
        {steps.map((step, index) => {
          const isCompleted = completedSteps.includes(step.number)
          const isCurrent = step.number === currentStep
          const isPast = step.number < currentStep

          return (
            <li key={step.number} className="relative flex-1">
              {index < steps.length - 1 && (
                <div
                  className={cn(
                    "absolute left-1/2 top-5 h-0.5 w-full",
                    isPast || isCompleted ? "bg-[#2786C2]" : "bg-[#E0E1DD]"
                  )}
                  style={{ transform: "translateX(50%)" }}
                />
              )}

              <div className="relative flex flex-col items-center group">
                <div
                  className={cn(
                    "relative z-10 flex h-10 w-10 items-center justify-center rounded-full border-2 bg-white transition-colors",
                    isCompleted || isPast
                      ? "border-[#2786C2] bg-[#2786C2]"
                      : isCurrent
                        ? "border-[#2786C2]"
                        : "border-[#E0E1DD]"
                  )}
                >
                  {isCompleted || isPast ? (
                    <Check className="h-5 w-5 text-white" />
                  ) : (
                    <span
                      className={cn(
                        "text-sm font-semibold",
                        isCurrent ? "text-[#2786C2]" : "text-[#778DA9]"
                      )}
                    >
                      {step.number}
                    </span>
                  )}
                </div>

                <div className="mt-2 text-center">
                  <span
                    className={cn(
                      "text-sm font-medium",
                      isCurrent ? "text-[#2786C2]" : "text-[#415A77]"
                    )}
                  >
                    {step.title}
                  </span>
                  {step.description && (
                    <p className="mt-0.5 max-w-[120px] text-xs text-[#778DA9]">
                      {step.description}
                    </p>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
