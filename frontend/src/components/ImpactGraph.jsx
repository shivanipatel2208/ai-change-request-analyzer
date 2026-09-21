import { useCallback, useMemo, useState } from 'react'
import { Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import '../styles/impact-graph.css'

/** Module 8: Impact & Dependency Graph.
 *
 * IMPORTANT data-honesty note: the AI Analysis Engine (Module 6) stores
 * affected_components and dependencies as two flat lists, each tied only to
 * the analysis itself - there is no stored "component X depends on
 * component Y" edge anywhere in the schema. So this graph does NOT draw
 * chains between individual components/dependencies (that would mean
 * inventing relationships the analysis never asserted). Instead it draws
 * exactly what the data supports: the change request branching into two
 * real categories - "Affected Components" and "Dependencies" - each
 * branching into the individual items the AI actually identified. The two
 * category nodes are a UI grouping only (clearly styled as such, dashed/
 * grey), not a claim about architecture.
 */

const IMPACT_COLORS = { critical: '#b42318', high: '#c4320a', medium: '#b54708', low: '#067647' }
const IMPACT_BADGE_CLASS = {
  critical: 'badge--red',
  high: 'badge--orange',
  medium: 'badge--amber',
  low: 'badge--green',
}

const ITEM_SPACING = 190
const HUB_Y = 140
const ITEM_Y = 300

function titleCase(value) {
  if (!value) return value
  return String(value).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function rowX(count, index, spacing = ITEM_SPACING) {
  if (count <= 1) return 0
  const totalWidth = (count - 1) * spacing
  return index * spacing - totalWidth / 2
}

function edge(source, target, impactLevel) {
  return {
    id: `e-${source}-${target}`,
    source,
    target,
    style: impactLevel
      ? { stroke: IMPACT_COLORS[impactLevel] || '#98a2b3', strokeWidth: 2 }
      : { stroke: '#d0d5dd', strokeWidth: 1.5 },
  }
}

/** Builds the node/edge arrays straight from the two real lists - nothing
 * here is inferred, only laid out for display. */
function layoutGraph(crCode, crTitle, components, dependencies) {
  const nodes = []
  const edges = []
  const hasComponents = components.length > 0
  const hasDependencies = dependencies.length > 0
  const compCenterX = hasComponents && hasDependencies ? -280 : 0
  const depCenterX = hasComponents && hasDependencies ? 280 : 0

  nodes.push({
    id: 'root',
    type: 'graphNode',
    position: { x: 0, y: 0 },
    data: { kind: 'root', name: crCode, subtitle: crTitle },
  })

  if (hasComponents) {
    nodes.push({
      id: 'hub-components',
      type: 'graphNode',
      position: { x: compCenterX, y: HUB_Y },
      data: { kind: 'hub', name: 'Affected Components' },
    })
    edges.push(edge('root', 'hub-components'))

    components.forEach((c, i) => {
      const id = `component-${c.id}`
      nodes.push({
        id,
        type: 'graphNode',
        position: { x: compCenterX + rowX(components.length, i), y: ITEM_Y },
        data: {
          kind: 'component',
          name: c.component_name,
          subtype: c.component_type,
          impact_level: c.impact_level,
          reason: c.reason,
          confidence: c.confidence,
        },
      })
      edges.push(edge('hub-components', id, c.impact_level))
    })
  }

  if (hasDependencies) {
    nodes.push({
      id: 'hub-dependencies',
      type: 'graphNode',
      position: { x: depCenterX, y: HUB_Y },
      data: { kind: 'hub', name: 'Dependencies' },
    })
    edges.push(edge('root', 'hub-dependencies'))

    dependencies.forEach((d, i) => {
      const id = `dependency-${d.id}`
      nodes.push({
        id,
        type: 'graphNode',
        position: { x: depCenterX + rowX(dependencies.length, i), y: ITEM_Y },
        data: {
          kind: 'dependency',
          name: d.dependency_name,
          subtype: d.dependency_type,
          impact_level: d.impact_level,
          reason: d.reason,
        },
      })
      edges.push(edge('hub-dependencies', id, d.impact_level))
    })
  }

  return { nodes, edges }
}

function GraphNode({ data }) {
  if (data.kind === 'root') {
    return (
      <div className="ig-node ig-node--root">
        <span className="ig-node-title">{data.name}</span>
        {data.subtitle && <span className="ig-node-sub">{data.subtitle}</span>}
        <Handle type="source" position={Position.Bottom} />
      </div>
    )
  }
  if (data.kind === 'hub') {
    return (
      <div className="ig-node ig-node--hub">
        <Handle type="target" position={Position.Top} />
        <span className="ig-node-title">{data.name}</span>
        <Handle type="source" position={Position.Bottom} />
      </div>
    )
  }
  const color = IMPACT_COLORS[data.impact_level] || '#98a2b3'
  return (
    <div className="ig-node ig-node--item" style={{ '--ig-color': color }}>
      <Handle type="target" position={Position.Top} />
      <span className="ig-node-kind">{data.kind === 'component' ? 'Component' : 'Dependency'}</span>
      <span className="ig-node-title">{data.name}</span>
      <span className="ig-node-type">{titleCase(data.subtype)}</span>
    </div>
  )
}

const NODE_TYPES = { graphNode: GraphNode }

function NodeDetailPanel({ node, onClose }) {
  return (
    <div className="ig-detail">
      <div className="ig-detail-header">
        <span className={`badge ${IMPACT_BADGE_CLASS[node.impact_level] || 'badge--gray'}`}>
          {titleCase(node.impact_level)} impact
        </span>
        <button type="button" className="ig-detail-close" onClick={onClose} aria-label="Close details">
          ×
        </button>
      </div>
      <h3 className="ig-detail-title">{node.name}</h3>
      <p className="ig-detail-type">
        {node.kind === 'component' ? 'Affected Component' : 'Dependency'} · {titleCase(node.subtype)}
      </p>

      <p className="ig-detail-label">Reason</p>
      <p className="ig-detail-text">{node.reason || 'Insufficient information.'}</p>

      {node.kind === 'component' && (
        <>
          <p className="ig-detail-label">Confidence</p>
          <div className="ig-detail-confidence">
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${Math.round(node.confidence)}%`, background: '#4338ca' }}
              />
            </div>
            <span className="ig-detail-confidence-value">{Math.round(node.confidence)}%</span>
          </div>
        </>
      )}

      {node.kind === 'dependency' && (
        <>
          <p className="ig-detail-label">Dependency Information</p>
          <p className="ig-detail-text">
            Type: {titleCase(node.subtype)} · {titleCase(node.impact_level)} impact
          </p>
        </>
      )}
    </div>
  )
}

/** The graph itself, embedded in the Analysis Dashboard's Impact tab.
 * `components`/`dependencies` are the exact arrays from GET .../analysis -
 * no separate fetch, no invented data. */
export default function ImpactGraph({ changeRequest, crCode, components, dependencies }) {
  const { nodes, edges } = useMemo(
    () => layoutGraph(crCode, changeRequest?.title || '', components, dependencies),
    [crCode, changeRequest, components, dependencies]
  )
  const [selected, setSelected] = useState(null)

  const onNodeClick = useCallback((_event, node) => {
    if (node.data.kind === 'component' || node.data.kind === 'dependency') {
      setSelected(node.data)
    } else {
      setSelected(null)
    }
  }, [])

  if (components.length === 0 && dependencies.length === 0) {
    return (
      <div className="ig-empty">
        <p className="ad-empty">
          No affected components or dependencies were identified for this change - nothing to graph yet.
        </p>
      </div>
    )
  }

  return (
    <div className="ig-shell">
      <div className="ig-canvas">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodeClick={onNodeClick}
            onPaneClick={() => setSelected(null)}
            fitView
            fitViewOptions={{ padding: 0.3 }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
            nodesConnectable={false}
            minZoom={0.3}
            maxZoom={1.5}
          >
            <Background gap={24} color="#e4e7ec" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
      </div>

      <div className="ig-sidebar">
        {selected ? (
          <NodeDetailPanel node={selected} onClose={() => setSelected(null)} />
        ) : (
          <div className="ig-hint">
            <p className="ad-empty">Click a node to see its reason, confidence, and dependency details.</p>
          </div>
        )}

        <div className="ig-legend">
          <span className="ig-legend-title">Impact Level</span>
          <span className="ig-legend-item">
            <i style={{ background: IMPACT_COLORS.critical }} /> Critical
          </span>
          <span className="ig-legend-item">
            <i style={{ background: IMPACT_COLORS.high }} /> High
          </span>
          <span className="ig-legend-item">
            <i style={{ background: IMPACT_COLORS.medium }} /> Medium
          </span>
          <span className="ig-legend-item">
            <i style={{ background: IMPACT_COLORS.low }} /> Low
          </span>
        </div>
      </div>
    </div>
  )
}
