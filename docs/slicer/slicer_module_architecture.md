# Slicer Module Architecture

This document summarizes Slicer module architecture concepts used by the SLIAFlow prototype.

## Core Concepts

3D Slicer is built around:

- the Slicer application core;
- the MRML scene;
- modules and extensions;
- libraries such as Qt, VTK, ITK, CTK, Python, and NumPy.

The current project uses a Python scripted loadable module because it provides full Slicer API access with a fast Reload and Reload and Test development loop.

## MRML Scene

The MRML scene is the shared data model for Slicer.

Important concepts:

- Data is stored in MRML nodes.
- Display properties belong in display nodes.
- Storage information belongs in storage nodes.
- Modules should communicate mainly through MRML nodes rather than direct module-to-module dependencies.
- Important workflow state should not live only in UI widgets.

Processing logic may read from and write to MRML nodes, but it should validate inputs before changing scene state.

## Module Entry Point

The module entry point should define:

- title;
- categories;
- contributors;
- help text;
- acknowledgement text;
- startup setup or sample-data registration when needed;
- public exports needed by Slicer.

Do not put feature logic in the module metadata class.

## Widget Responsibility

The widget is responsible for:

- loading the Qt `.ui` file or constructing UI controls;
- connecting buttons, selectors, and other signals;
- reading current UI values;
- calling logic methods;
- displaying results and validation messages;
- synchronizing UI state with a parameter node when one is used.

The widget should not contain processing algorithms, file parsing, or reusable computation.

## Logic Responsibility

The logic class is responsible for:

- computation;
- input validation;
- MRML node inspection;
- measurements and coordinate conversion;
- data conversion;
- report or result helpers when they are not UI-specific.

Logic should not depend on the widget. Logic methods should be callable from the UI, tests, another module, or the Python console.

Use passive logic by default: the widget creates or owns the logic instance, and the logic acts only when called. Add scene observers or background behavior only when a task requires them.

## Test Responsibility

Scripted-module tests should exercise logic and important integration paths. Prefer tests that can run without manual UI clicking.

Tests should use in-memory placeholder fixtures, public Slicer sample data, anonymized test data, mock results, or explicitly approved public medical data.

## Parameter Nodes

Parameter nodes store module state in the MRML scene.

Use a parameter node when:

- settings must survive scene save and load;
- multiple inputs are linked as workflow state;
- UI state must stay synchronized with MRML state;
- the workflow is too complex for transient widget-only state.

Avoid adding parameter-node complexity before the workflow needs persisted state.

## Qt UI Files

For scripted modules with a `.ui` file, keep UI layout in `Resources/UI/` and behavior in the widget class.

After changing a `.ui` file, Reload may be enough. Restart Slicer if the UI does not refresh cleanly.

## Common Mistakes

- Putting all feature logic in the widget.
- Letting logic depend on widget controls.
- Storing important state only in UI fields.
- Changing MRML nodes without validating inputs.
- Ignoring units or coordinate systems in names.
- Adding real clinical or algorithmic claims before validation boundaries exist.
- Adding dependencies or sample data without an approved task.
