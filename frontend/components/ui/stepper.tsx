import { Check } from "lucide-react"
import { WizardStep } from "@/types/schema"

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
              {/* Connecting line */}
              {index < steps.length - 1 && (
                <div
                  className={`absolute top-5 left-1/2 w-full h-0.5 ${
                    isPast || isCompleted ? "bg-blue-600" : "bg-slate-200"
                  }`}
                  style={{ transform: "translateX(50%)" }}
                />
              )}

              {/* Step indicator */}
              <div className="relative flex flex-col items-center group">
                <div
                  className={`relative z-10 flex items-center justify-center w-10 h-10 rounded-full border-2 ${
                    isCompleted || isPast
                      ? "bg-blue-600 border-blue-600"
                      : isCurrent
                      ? "bg-white border-blue-600"
                      : "bg-white border-slate-300"
                  }`}
                >
                  {isCompleted || isPast ? (
                    <Check className="h-5 w-5 text-white" />
                  ) : (
                    <span
                      className={`text-sm font-semibold ${
                        isCurrent ? "text-blue-600" : "text-slate-500"
                      }`}
                    >
                      {step.number}
                    </span>
                  )}
                </div>

                {/* Step label */}
                <div className="mt-2 text-center">
                  <span
                    className={`text-sm font-medium ${
                      isCurrent ? "text-blue-600" : "text-slate-700"
                    }`}
                  >
                    {step.title}
                  </span>
                  {step.description && (
                    <p className="text-xs text-slate-500 mt-0.5 max-w-[120px]">
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
