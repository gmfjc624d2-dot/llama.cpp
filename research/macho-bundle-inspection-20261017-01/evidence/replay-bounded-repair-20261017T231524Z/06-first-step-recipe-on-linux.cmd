cwd: /home/user/llama.cpp/research/macho-bundle-inspection-20261017-01
start_utc: 2026-10-17T23:16:51Z
argv: python3 -I -c import\ importlib.util\,\ json\;\ s\ =\ importlib.util.spec_from_file_location\(\"rb\"\,\ \"scripts/replay_bounded.py\"\)\;\ m\ =\ importlib.util.module_from_spec\(s\)\;\ s.loader.exec_module\(m\)\;\ r\,\ o\,\ e\ =\ m.run_case\(\[\"/usr/bin/uname\"\,\ \"-a\"\]\,\ \".\"\,\ 5.0\,\ 4096\,\ 4096\,\ 1.0\)\;\ print\(json.dumps\(\{k:\ r\[k\]\ for\ k\ in\ \(\"rc\"\,\ \"process\"\,\ \"cleanup\"\,\ \"summary\"\)\}\,\ indent=1\)\)\;\ print\(o.decode\(\"utf-8\"\,\ \"replace\"\)\)
end_utc: 2026-10-17T23:16:51Z
