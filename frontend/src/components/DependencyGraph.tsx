import { useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import type { GraphView } from '../api/types';
export function DependencyGraph({ graph, onSelect }: { graph: GraphView; onSelect: (id: string) => void }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || graph.nodes.length === 0) return;
    const cy = cytoscape({ container: element.current,
      elements: [...graph.nodes.map(node => ({ data: { id: node.id, label: node.label, name: node.coordinate?.name ?? node.label, state: node.query_status } })), ...graph.edges.map(edge => ({ data: { id: edge.id, source: edge.source, target: edge.target } }))],
      style: [
        { selector: 'node', style: { label: '', 'background-color': '#7896a4', color: '#293f4a', 'font-size': 10, 'text-valign': 'bottom', 'text-margin-y': 8, width: 21, height: 21, 'border-width': 3, 'border-color': '#eef5f5', 'text-max-width': '120px', 'text-wrap': 'wrap' } },
        { selector: 'node[state="matched"]', style: { 'background-color': '#dc7b53', 'border-color': '#fce9df', label: 'data(name)', 'font-size': 12 } },
        { selector: 'node[state="error"],node[state="partial"],node[state="conflict"],node[state="unqueried"]', style: { 'background-color': '#bd9b50' } },
        { selector: 'edge', style: { width: 1, 'line-color': '#d0dee0', 'target-arrow-color': '#b5c8cc', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', opacity: 0.8 } },
        { selector: ':selected', style: { label: 'data(label)', 'border-color': '#108a7f', 'border-width': 5 } },
        { selector: '.show-label', style: { label: 'data(label)' } },
      ], layout: { name: 'breadthfirst', directed: true, padding: 45, spacingFactor: 1.3 }, minZoom: .18, maxZoom: 3, wheelSensitivity: .18 });
    cy.on('tap', 'node', event => onSelect(event.target.id()));
    cy.on('zoom', () => { cy.nodes().toggleClass('show-label', cy.zoom() >= 1.15); });
    return () => cy.destroy();
  }, [graph, onSelect]);
  return <div className="graph-canvas" ref={element} role="img" aria-label="Dependency graph; select a package from the accessible table below" />;
}
