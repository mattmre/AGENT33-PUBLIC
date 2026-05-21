export interface OnboardingStep {
  step_id: string;
  category: string;
  title: string;
  description: string;
  completed: boolean;
  remediation: string;
}

export interface OnboardingStatus {
  steps: OnboardingStep[];
  completed_count: number;
  total_count: number;
  overall_complete: boolean;
}
