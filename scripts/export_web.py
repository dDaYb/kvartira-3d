"""Выгрузка текущей сцены в GLB для сайта. Исходный blend не сохраняется."""
import json
import sys
from datetime import datetime
from pathlib import Path

import bpy

SCENE_NAME = "АДС — исправленная расстановка"
CEILING_MARKERS = ("потолок", "потолка")


def args_after_double_dash():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Нужны пути: blend, glb, info.json")
    extra = argv[argv.index("--") + 1 :]
    if len(extra) != 3:
        raise SystemExit("Нужны три аргумента: blend, glb, info.json")
    return extra


def activate_scene(scene):
    window = bpy.context.window_manager.windows[0]
    window.scene = scene
    if scene.view_layers:
        window.view_layer = scene.view_layers[0]
    bpy.context.view_layer.update()
    return window.view_layer


def is_ceiling(obj):
    name = obj.name.casefold()
    return any(marker in name for marker in CEILING_MARKERS)


def choose_meshes(scene, view_layer):
    chosen = []
    skipped_ceiling = 0
    skipped_hidden = 0
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if is_ceiling(obj):
            skipped_ceiling += 1
            continue
        if obj.hide_render or not obj.visible_get(view_layer=view_layer):
            skipped_hidden += 1
            continue
        chosen.append(obj)
    return chosen, skipped_ceiling, skipped_hidden


def export_glb(filepath, selected_only):
    kwargs = {
        "filepath": filepath,
        "export_format": "GLB",
        "use_selection": selected_only,
        "use_visible": True,
        "use_renderable": True,
        "export_apply": True,
        "export_cameras": False,
        "export_lights": True,
        "export_image_format": "JPEG",
        "export_jpeg_quality": 82,
        "export_draco_mesh_compression_enable": True,
        "export_draco_mesh_compression_level": 6,
    }
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    accepted = {key: value for key, value in kwargs.items() if key in props or key == "filepath"}
    missing = sorted(set(kwargs) - set(accepted))
    if missing:
        print("EXPORT_SKIPPED_ARGS", ", ".join(missing))
    result = bpy.ops.export_scene.gltf(**accepted)
    if "FINISHED" not in result:
        raise SystemExit(f"Экспорт glTF не завершился: {result}")


def main():
    blend_path, glb_path, info_path = args_after_double_dash()
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    if SCENE_NAME not in bpy.data.scenes:
        names = ", ".join(scene.name for scene in bpy.data.scenes)
        raise SystemExit(f"В файле нет сцены {SCENE_NAME!r}. Есть: {names}")

    scene = bpy.data.scenes[SCENE_NAME]
    view_layer = activate_scene(scene)
    chosen, skipped_ceiling, skipped_hidden = choose_meshes(scene, view_layer)
    if not chosen:
        raise SystemExit("Нечего выгружать: видимых сеток без потолков не найдено")

    for obj in scene.objects:
        obj.select_set(False)
    for obj in chosen:
        obj.select_set(True)
    view_layer.objects.active = chosen[0]

    Path(glb_path).parent.mkdir(parents=True, exist_ok=True)
    export_glb(glb_path, selected_only=True)

    size = Path(glb_path).stat().st_size
    info = {
        "title": "Квартира — промежуточная модель",
        "exported": datetime.now().astimezone().isoformat(timespec="minutes"),
        "source": Path(blend_path).name,
        "scene": SCENE_NAME,
        "blender": bpy.app.version_string,
        "meshes": len(chosen),
        "ceilings_omitted": skipped_ceiling,
        "hidden_omitted": skipped_hidden,
        "bytes": size,
        "note": (
            "Промежуточная визуализация для просмотра объёма. "
            "Потолки скрыты, чтобы комнаты были видны сверху. "
            "Отделка, мебель и свет не утверждены и не являются закупкой."
        ),
    }
    Path(info_path).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXPORT_OK", glb_path, size, "meshes", len(chosen))


if __name__ == "__main__":
    main()
