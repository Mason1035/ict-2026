idf_component_register(SRCS "logic.cpp" "risk_framework.cpp" INCLUDE_DIRS "include" REQUIRES node_contracts)
target_compile_options(${COMPONENT_LIB} PRIVATE -ffp-contract=off)
