set(MODULE_NAME SLIAFlow)

set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ${MODULE_NAME}Lib/__init__.py
  ${MODULE_NAME}Lib/${MODULE_NAME}Logic.py
  ${MODULE_NAME}Lib/${MODULE_NAME}ParameterNode.py
  ${MODULE_NAME}Lib/${MODULE_NAME}Widget.py
  ${MODULE_NAME}Lib/${MODULE_NAME}Test.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/UI/${MODULE_NAME}.ui
  Resources/requirements.txt
  )

slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

if(BUILD_TESTING)
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)
endif()
