// The same payloads as in contract-fixtures/ (see the README there), here as
// typed objects: the compiler checks them against the TS types, the test
// checks that they match the JSON files the Python side validates as well.

import { describe, expect, it } from 'vitest'
import type { LiveActivityState, NativeContentDef, NativeFormDef, Widget } from '../src/index.js'
import widgetsJson from '../../../contract-fixtures/widgets.json'
import liveActivityStateJson from '../../../contract-fixtures/live-activity-state.json'
import nativeFormJson from '../../../contract-fixtures/native-form.json'
import nativeContentJson from '../../../contract-fixtures/native-content.json'

const widgets: Widget[] = [
  {
    id: 'open-orders',
    kind: 'kpi',
    title: 'Open orders',
    icon: 'shippingbox',
    tint: '#2e4a62',
    path: '/orders',
    updatedAt: '2026-09-29T08:00:00Z',
    data: {
      value: 12,
      unit: 'pcs',
      caption: 'since Monday',
      trend: { direction: 'up', text: '+3', positive: false },
    },
  },
  {
    id: 'week',
    kind: 'stats',
    size: 'medium',
    title: 'This week',
    data: {
      items: [
        { label: 'Visits', value: 14 },
        { label: 'Umsatz', value: "CHF 12'400", trend: { direction: 'flat' } },
      ],
    },
  },
  {
    id: 'approvals',
    kind: 'list',
    title: 'To approve',
    data: {
      maxVisible: 3,
      emptyText: 'Nothing open',
      items: [
        {
          id: 'A-1001',
          title: 'Vacation request',
          subtitle: 'M. Muster',
          trailing: '3 days',
          path: '/approvals/A-1001',
          actions: [
            { id: 'approve', label: 'Approve', biometric: true },
            {
              id: 'reject',
              label: 'Reject',
              style: 'destructive',
              confirm: 'Really reject?',
            },
          ],
        },
      ],
    },
  },
  {
    id: 'revenue',
    kind: 'chart',
    data: {
      type: 'line',
      unit: 'CHF',
      series: [
        {
          name: '2026',
          color: '#e60014',
          points: [
            { x: 'Jan', y: 10.5 },
            { x: 'Feb', y: 12 },
          ],
        },
      ],
    },
  },
  {
    id: 'target',
    kind: 'progress',
    data: { value: 0.6, total: 1, caption: '60 % vom Ziel', style: 'ring' },
  },
  {
    id: 'hint',
    kind: 'text',
    defaultEnabled: false,
    data: { markdown: '**New:** Scan directly from the app', linkLabel: 'More' },
  },
  {
    id: 'new-visit',
    kind: 'action',
    required: true,
    data: {
      text: 'Record visit',
      pages: [
        {
          title: 'Customer',
          fields: [
            {
              id: 'customer',
              type: 'search',
              label: 'Customer',
              minQueryLength: 0,
              required: true,
            },
            { id: 'express', type: 'toggle', label: 'Express', value: false },
          ],
        },
        {
          fields: [
            { id: 'reason', label: 'Reason', visibleIf: { field: 'express', equals: true } },
            {
              id: 'article',
              type: 'select',
              options: [{ value: 'A1', label: 'Item 1' }, { value: 'A2' }],
            },
            { id: 'contact', type: 'select', remote: true, value: 'c-1', valueLabel: 'Anna' },
          ],
        },
      ],
      buttons: [{ id: 'save', label: 'Speichern', icon: 'checkmark' }],
    },
  },
  {
    id: 'news',
    kind: 'news',
    size: 'tall',
    data: {
      emptyText: 'No news',
      items: [
        {
          id: 'n-1',
          title: 'New location',
          text: 'From October in Bern.',
          imageUrl: '/img/bern.jpg',
          path: '/news/n-1',
          date: '2026-09-28T10:00:00Z',
          caption: 'HR',
          channels: ['internal'],
        },
      ],
    },
  },
  {
    id: 'new-customer',
    kind: 'action',
    data: {
      text: 'Create a customer',
      fields: [
        {
          id: 'name',
          type: 'text',
          label: 'Company name',
          required: true,
          minLength: 2,
          maxLength: 80,
        },
        {
          id: 'email',
          type: 'email',
          label: 'Email',
          pattern: '^[^@\\s]+@[^@\\s]+$',
          patternMessage: 'Please enter a valid email address',
        },
        {
          id: 'notes',
          type: 'textarea',
          label: 'Notes',
          help: 'Visible to your team',
          maxLength: 500,
        },
        { id: 'seats', type: 'stepper', label: 'Seats', min: 1, max: 20, step: 1, value: 1 },
        {
          id: 'tags',
          type: 'multiselect',
          label: 'Tags',
          options: [{ value: 'vip', label: 'VIP' }, { value: 'new' }],
        },
        {
          id: 'card',
          type: 'photo',
          label: 'Business card',
          max: 1,
          source: 'camera',
          maxDimension: 2048,
        },
      ],
      buttons: [{ id: 'create', label: 'Create', icon: 'checkmark' }],
    },
  },
]

const liveActivityState: LiveActivityState = {
  title: 'Order is being packed',
  subtitle: 'Zürich branch',
  status: 'Packing',
  steps: ['Ordered', 'Packed', 'Ready for pickup'],
  currentStep: 1,
  icon: 'shippingbox',
  tint: '#2e4a62',
}

const nativeForm: NativeFormDef = {
  id: 'new-customer',
  title: 'New customer',
  size: 'large',
  tint: '#2e4a62',
  text: 'Fill in the basic data.',
  values: { type: 'b2b' },
  context: { source: 'customer-list' },
  pages: [
    {
      title: 'Company',
      fields: [
        {
          id: 'name',
          type: 'text',
          label: 'Company name',
          required: true,
          minLength: 2,
          maxLength: 80,
        },
        {
          id: 'type',
          type: 'segmented',
          label: 'Type',
          options: [
            { value: 'b2b', label: 'B2B' },
            { value: 'b2c', label: 'B2C' },
          ],
        },
        {
          id: 'vat',
          type: 'text',
          label: 'VAT number',
          placeholder: 'CHE-123.456.789',
          pattern: '^CHE-\\d{3}\\.\\d{3}\\.\\d{3}$',
          patternMessage: 'Format: CHE-123.456.789',
          visibleIf: { field: 'type', equals: 'b2b' },
        },
        { id: 'founded', type: 'date', label: 'Founded' },
        { id: 'employees', type: 'number', label: 'Employees', min: 0, max: 100000 },
      ],
    },
    {
      title: 'Contact',
      text: 'How do we reach them?',
      fields: [
        { id: 'email', type: 'email', label: 'Email', required: true },
        { id: 'phone', type: 'phone', label: 'Phone' },
        { id: 'website', type: 'url', label: 'Website', placeholder: 'https://example.com' },
        {
          id: 'owner',
          type: 'search',
          label: 'Account manager',
          minQueryLength: 2,
          value: 'u-1',
          valueLabel: 'Anna Muster',
        },
        {
          id: 'channels',
          type: 'multiselect',
          label: 'Channels',
          options: [
            { value: 'mail', label: 'Mail' },
            { value: 'phone', label: 'Phone', subtitle: 'Office hours only' },
          ],
          value: ['mail'],
        },
        {
          id: 'priority',
          type: 'select',
          label: 'Priority',
          options: [{ value: 'high', label: 'High' }, { value: 'low' }],
        },
        { id: 'vip', type: 'toggle', label: 'VIP', value: false },
        { id: 'seats', type: 'stepper', label: 'Seats', min: 1, max: 20, step: 1 },
        { id: 'callback', type: 'datetime', label: 'Call back on' },
        { id: 'opens', type: 'time', label: 'Opens at', value: '08:00' },
        {
          id: 'notes',
          type: 'textarea',
          label: 'Notes',
          help: 'Visible to the whole team.',
          maxLength: 500,
        },
      ],
    },
    {
      title: 'Documents',
      fields: [
        { id: 'customer_no', type: 'info', label: 'Customer number', value: 'on save' },
        {
          id: 'card',
          type: 'photo',
          label: 'Business card',
          max: 1,
          source: 'both',
          maxDimension: 2048,
        },
        { id: 'contract', type: 'scan', label: 'Contract', format: 'pdf', max: 5 },
        { id: 'signature', type: 'signature', label: 'Signature', required: true },
        { id: 'gln', type: 'barcode', label: 'GLN', symbologies: ['ean13', 'qr'] },
        {
          id: 'lines',
          type: 'repeat',
          label: 'Order lines',
          min: 1,
          max: 20,
          addLabel: 'Add line',
          fields: [
            {
              id: 'article',
              type: 'select',
              label: 'Article',
              options: [{ value: 'A1', label: 'Screws M6' }],
            },
            { id: 'qty', type: 'stepper', label: 'Quantity', min: 1 },
          ],
        },
      ],
    },
  ],
  submit: {
    label: 'Create customer',
    confirm: 'Create this customer?',
    biometric: false,
    style: 'primary',
    wait: true,
  },
}

const nativeContent: NativeContentDef = {
  id: 'customer-123',
  title: 'Miller Ltd',
  subtitle: 'Customer 123',
  size: 'medium',
  tint: '#2e4a62',
  context: { customerId: '123' },
  blocks: [
    {
      type: 'image',
      url: 'https://example.com/logo.png',
      alt: 'Company logo',
      caption: 'Since 1998',
      height: 140,
      fit: 'fit',
      shape: 'rounded',
      tapToZoom: true,
    },
    { type: 'image', data: 'data:image/png;base64,iVBORw0KGgo=', shape: 'circle' },
    { type: 'heading', text: 'Overview', level: 2, icon: 'building.2' },
    {
      type: 'badges',
      items: [{ text: 'Key account', tint: '#2e4a62', icon: 'star' }, { text: 'Zurich' }],
    },
    {
      type: 'facts',
      items: [
        { label: 'Phone', value: '+41 44 000 00 00', kind: 'phone', icon: 'phone' },
        { label: 'Email', value: 'info@example.com', kind: 'email', copyable: true },
        { label: 'Address', value: 'Bahnhofstrasse 1, 8001 Zurich', kind: 'address' },
        { label: 'Website', value: 'https://example.com', kind: 'url' },
        { label: 'Customer since', value: '2019', kind: 'text' },
      ],
    },
    {
      type: 'text',
      markdown: 'Prefers **delivery on Tuesdays**.',
      style: 'body',
      align: 'leading',
    },
    { type: 'text', markdown: 'Updated today', style: 'footnote', align: 'trailing' },
    {
      type: 'callout',
      style: 'warning',
      title: 'Credit limit',
      text: '81 % of the limit is used.',
    },
    { type: 'kpi', data: { value: 12, unit: 'pcs', caption: 'open orders' } },
    {
      type: 'stats',
      data: {
        items: [
          { label: 'Visits', value: 14 },
          { label: 'Revenue', value: "CHF 12'400", trend: { direction: 'up' } },
        ],
      },
    },
    {
      type: 'chart',
      data: {
        type: 'line',
        unit: 'CHF k',
        series: [
          {
            name: '2026',
            points: [
              { x: 'Jan', y: 42 },
              { x: 'Feb', y: 51 },
            ],
          },
        ],
      },
    },
    {
      type: 'progress',
      data: { value: 0.6, total: 1, caption: 'of the yearly target', style: 'ring' },
    },
    {
      type: 'table',
      caption: 'Last orders',
      columns: [
        { key: 'no', label: 'No.' },
        { key: 'amount', label: 'Amount', align: 'trailing' },
      ],
      rows: [
        { no: 'A-1001', amount: 240 },
        { no: 'A-1002', amount: "CHF 1'200" },
      ],
    },
    {
      type: 'list',
      items: [
        {
          title: 'Anna Muster',
          subtitle: 'Purchasing',
          trailing: 'Main contact',
          icon: 'person',
          action: { id: 'open-contact', label: 'Open', then: [{ openPath: '/contacts/1' }] },
        },
        { title: 'Beat Keller', image: 'https://example.com/beat.jpg' },
      ],
    },
    {
      type: 'map',
      latitude: 47.3769,
      longitude: 8.5417,
      name: 'Head office',
      span: 800,
      height: 160,
    },
    {
      type: 'file',
      url: 'https://example.com/files/contract.pdf',
      name: 'Contract.pdf',
      mime: 'application/pdf',
    },
    {
      type: 'video',
      url: 'https://example.com/files/intro.mp4',
      poster: 'https://example.com/files/intro.jpg',
    },
    {
      type: 'card',
      title: 'Notes',
      blocks: [
        {
          type: 'row',
          blocks: [
            { type: 'kpi', data: { value: 3, caption: 'calls' } },
            { type: 'kpi', data: { value: 1, caption: 'complaints' } },
          ],
        },
        { type: 'divider' },
        { type: 'spacer', height: 8 },
      ],
    },
    {
      type: 'fields',
      fields: [{ id: 'comment', type: 'textarea', label: 'Comment', maxLength: 200 }],
    },
    {
      type: 'buttons',
      items: [
        {
          id: 'share',
          label: 'Share',
          style: 'secondary',
          icon: 'square.and.arrow.up',
          then: [{ share: { text: 'Miller Ltd', url: 'https://example.com/customers/123' } }],
        },
        { id: 'copy-number', label: 'Copy number', then: [{ copy: '123' }] },
      ],
    },
  ],
  actions: [
    { id: 'new-order', label: 'New order', style: 'primary', icon: 'plus', wait: true },
    {
      id: 'route',
      label: 'Route',
      style: 'secondary',
      icon: 'location',
      then: [
        {
          device: {
            action: 'navigate',
            destination: { address: 'Bahnhofstrasse 1, 8001 Zurich' },
          },
        },
      ],
    },
    { id: 'save-comment', label: 'Save comment', submit: true, wait: true },
    {
      id: 'delete',
      label: 'Delete',
      style: 'destructive',
      confirm: 'Really delete this customer?',
      biometric: true,
      then: [
        { openUrl: 'https://example.com/customers/123/deleted' },
        {
          showContent: {
            title: 'Deleted',
            size: 'fit',
            blocks: [{ type: 'callout', style: 'success', text: 'The customer was deleted.' }],
            actions: [{ id: 'done', label: 'Done', then: [{ close: true }] }],
          },
        },
        {
          showForm: {
            title: 'Why?',
            size: 'fit',
            fields: [{ id: 'reason', type: 'textarea', label: 'Reason' }],
          },
        },
      ],
    },
  ],
}

describe('contract-fixtures', () => {
  it('widgets match widgets.json', () => {
    expect(widgets).toEqual(widgetsJson)
  })

  it('LiveActivityState matches live-activity-state.json', () => {
    expect(liveActivityState).toEqual(liveActivityStateJson)
  })

  it('NativeFormDef matches native-form.json', () => {
    expect(nativeForm).toEqual(nativeFormJson)
  })

  it('NativeContentDef matches native-content.json', () => {
    expect(nativeContent).toEqual(nativeContentJson)
  })
})
