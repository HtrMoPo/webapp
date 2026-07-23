<script setup>
import { computed, ref, watch } from 'vue'

// Plain filter-as-you-type combobox: with 50+ catalog entries a flat
// `<select>` is unusable to scan, but the catalog is small enough that
// client-side substring filtering needs no debounce/backend search.
const props = defineProps({
  modelValue: { type: String, default: '' }, // selected option's `value`
  options: { type: Array, required: true }, // [{ value, label }]
  placeholder: { type: String, default: '' },
  clearable: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const query = ref('')
const open = ref(false)
const rootEl = ref(null)

const selectedLabel = computed(() => props.options.find((o) => o.value === props.modelValue)?.label || '')

// Shows the selected option's label when idle, but whatever's being typed
// while the dropdown is open/being edited.
watch(
  () => props.modelValue,
  () => {
    if (!open.value) query.value = selectedLabel.value
  },
  { immediate: true }
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  const opts = q ? props.options.filter((o) => o.label.toLowerCase().includes(q)) : props.options
  return opts.slice(0, 50)
})

function onFocus() {
  open.value = true
  query.value = ''
}
function select(option) {
  emit('update:modelValue', option.value)
  query.value = option.label
  open.value = false
}
function clear() {
  emit('update:modelValue', '')
  query.value = ''
  open.value = false
}
function onClickOutside(e) {
  if (rootEl.value && !rootEl.value.contains(e.target)) {
    open.value = false
    query.value = selectedLabel.value
  }
}

function bind() {
  document.addEventListener('mousedown', onClickOutside)
}
function unbind() {
  document.removeEventListener('mousedown', onClickOutside)
}
watch(open, (v) => (v ? bind() : unbind()))
</script>

<template>
  <div class="model-autocomplete" ref="rootEl">
    <div class="model-autocomplete__input-wrap">
      <input
        class="form-input"
        type="text"
        :placeholder="placeholder"
        v-model="query"
        @focus="onFocus"
      />
      <button
        v-if="clearable && modelValue"
        type="button"
        class="model-autocomplete__clear"
        @mousedown.prevent="clear"
      >×</button>
    </div>
    <ul v-if="open" class="model-autocomplete__list">
      <li v-if="!filtered.length" class="model-autocomplete__empty">No match</li>
      <li
        v-for="o in filtered"
        :key="o.value"
        class="model-autocomplete__option"
        :class="{ 'is-selected': o.value === modelValue }"
        @mousedown.prevent="select(o)"
      >{{ o.label }}</li>
    </ul>
  </div>
</template>

<style scoped>
.model-autocomplete { position: relative; }
.model-autocomplete__input-wrap { position: relative; }
.model-autocomplete__clear {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  border: none; background: none; color: var(--ink-3); font-size: 18px;
  line-height: 1; cursor: pointer; padding: 2px 4px;
}
.model-autocomplete__clear:hover { color: var(--ink); }
.model-autocomplete__list {
  position: absolute; z-index: 20; top: calc(100% + 4px); left: 0; right: 0;
  max-height: 260px; overflow-y: auto; margin: 0; padding: 6px;
  background: var(--surface); border: 1px solid var(--line-2); border-radius: 8px;
  box-shadow: var(--shadow-sm); list-style: none;
}
.model-autocomplete__option {
  padding: 7px 9px; border-radius: 6px; font-size: 13.5px; color: var(--ink-2);
  cursor: pointer;
}
.model-autocomplete__option:hover { background: var(--paper-2); }
.model-autocomplete__option.is-selected { background: var(--olive-tint-2); color: var(--olive-deep); font-weight: 600; }
.model-autocomplete__empty { padding: 7px 9px; font-size: 13px; color: var(--ink-3); }
</style>
