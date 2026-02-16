type PickerInput = HTMLInputElement & { showPicker?: () => void }

export function openNativePicker(input: HTMLInputElement | null, clickFallback = false): void {
  if (!input) return
  const picker = input as PickerInput
  if (typeof picker.showPicker === "function") {
    try {
      picker.showPicker()
      return
    } catch {
      // no-op
    }
  }
  try {
    if (clickFallback) {
      input.click()
      return
    }
    input.focus()
  } catch {
    // no-op
  }
}
