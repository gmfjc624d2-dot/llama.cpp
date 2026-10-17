# Replay outcomes: linux-llvm

Tool parse outcomes only. `parsed_by_tool` does not mean dyld would load the file; every other value is not passing.

| file | lipo -archs | arm64 -l / -L | x86_64 -l / -L | all -l |
|---|---|---|---|---|
| bundles/dist/README.txt | rc 1 | not_object / not_object | not_object / not_object | not_object |
| bundles/dist/libggml-base.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/dist/libggml-cpu.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/dist/libggml.0.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/dist/libllama.dylib | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
| bundles/dist/llama-cli | arm64 | parsed_by_tool / parsed_by_tool | arch_absent / arch_absent | parsed_by_tool |
