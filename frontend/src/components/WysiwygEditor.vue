<script setup>
import Quill from 'quill'
import 'quill/dist/quill.snow.css'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])

const editorEl = ref(null)
let quill = null

onMounted(() => {
  quill = new Quill(editorEl.value, {
    theme: 'snow',
    modules: {
      toolbar: [
        [{ header: [2, 3, false] }],
        ['bold', 'italic'],
        [{ list: 'ordered' }, { list: 'bullet' }],
        ['link', 'blockquote', 'code-block'],
        ['clean'],
      ],
    },
  })
  if (props.modelValue) quill.root.innerHTML = props.modelValue
  quill.on('text-change', () => {
    const html = quill.root.innerHTML === '<p><br></p>' ? '' : quill.root.innerHTML
    emit('update:modelValue', html)
  })
})

watch(
  () => props.modelValue,
  (val) => {
    if (quill && val !== quill.root.innerHTML) quill.root.innerHTML = val || ''
  }
)

onBeforeUnmount(() => {
  quill = null
})
</script>

<template>
  <div ref="editorEl"></div>
</template>

<style scoped>
:deep(.ql-toolbar) {
  border-color: var(--line-2);
  border-radius: 8px 8px 0 0;
  font-family: var(--sans);
}
:deep(.ql-container) {
  border-color: var(--line-2);
  border-radius: 0 0 8px 8px;
  font-family: var(--sans);
  font-size: 14px;
  min-height: 180px;
}
:deep(.ql-editor) {
  min-height: 180px;
}
</style>
