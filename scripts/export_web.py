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
        "export_image_format": "AUTO",
        "export_jpeg_quality": 85,
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


# Крупные поверхности, у которых Cycles-узлы не доезжают до glTF.
BAKE_MATERIALS = (
    "R29 Стены — серый.001",
    "LV штукатурка",
    "P10 Краска за диваном — A и B",
    "LV ёлочка дуб",
    "P12 Кварцпаркет светлый дуб",
    "F29 A2 — светлый серый",
    "MB Пол",
    "V2 Крупный керамогранит",
    "P15 Оливковая квадратная плитка",
    "R27 Вертикальная плитка False",
    "R27 Вертикальная плитка True",
    "P06 Неотбелённый лён",
    "P06 Оливковая обивка",
    "P06 Серо-бежевый текстиль",
    "R27 Оливковый велюр",
    "P02 Оливковая ткань",
    "R27 Светлый натуральный ковёр",
    "R27 Орех",
    "P03 Натуральный дуб",
)
HI_RES = {
    "R29 Стены — серый.001",
    "LV штукатурка",
    "P10 Краска за диваном — A и B",
    "LV ёлочка дуб",
    "P12 Кварцпаркет светлый дуб",
    "F29 A2 — светлый серый",
    "MB Пол",
    "V2 Крупный керамогранит",
    "P15 Оливковая квадратная плитка",
}


def principled_node(mat):
    if not mat or not mat.node_tree:
        return None
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            return node
    return None


def needs_bake(mat):
    node = principled_node(mat)
    if node is None:
        return False
    for name in ("Base Color", "Roughness", "Normal"):
        sock = node.inputs.get(name)
        if sock and sock.is_linked:
            return True
    return False


def prepare_bake_color(scene):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.cycles.device = "CPU"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.render.bake.margin = 8
    scene.render.bake.use_clear = True


def new_bake_image(name, size, data):
    image = bpy.data.images.new(name, size, size, alpha=False)
    image.colorspace_settings.name = "Non-Color" if data else "sRGB"
    image.file_format = "PNG" if data else "JPEG"
    return image


def bake_plane(scene, mat, size_m):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.mesh.primitive_plane_add(size=size_m, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "WEB_BAKE_PLANE"
    plane.data.materials.append(mat)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0)
    bpy.ops.object.mode_set(mode="OBJECT")
    return plane


def bake_pass(scene, plane, mat, image, bake_type, pass_filter):
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.select = True
    mat.node_tree.nodes.active = node
    kwargs = {"type": bake_type, "use_clear": True, "margin": 8}
    if pass_filter:
        kwargs["pass_filter"] = pass_filter
    with bpy.context.temp_override(
        scene=scene,
        view_layer=scene.view_layers[0],
        active_object=plane,
        object=plane,
        selected_objects=[plane],
        selected_editable_objects=[plane],
    ):
        bpy.ops.object.bake(**kwargs)
    mat.node_tree.nodes.remove(node)


def assign_baked_material(mat, color_img, rough_img, normal_img, rough_value, metallic):
    tree = mat.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-200, 0)
    bsdf.inputs["Roughness"].default_value = rough_value
    bsdf.inputs["Metallic"].default_value = metallic
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    def add_image(image, x, y):
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.location = (x, y)
        return node

    if color_img:
        tree.links.new(add_image(color_img, -700, 200).outputs["Color"], bsdf.inputs["Base Color"])
    if rough_img:
        tree.links.new(add_image(rough_img, -700, -50).outputs["Color"], bsdf.inputs["Roughness"])
    if normal_img:
        normal = tree.nodes.new("ShaderNodeNormalMap")
        normal.location = (-400, -250)
        tree.links.new(add_image(normal_img, -700, -300).outputs["Color"], normal.inputs["Color"])
        tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])


def project_uv(objects, cube_size):
    if not objects:
        return
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    unique = []
    seen = set()
    for obj in objects:
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        if obj.data in seen:
            continue
        seen.add(obj.data)
        if not obj.data.uv_layers:
            obj.data.uv_layers.new(name="WebUV")
        obj.data.uv_layers.active_index = 0
        unique.append(obj)
        obj.select_set(True)
    if not unique:
        return
    bpy.context.view_layer.objects.active = unique[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.cube_project(
        cube_size=cube_size,
        correct_aspect=False,
        clip_to_bounds=False,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")


def objects_using(material, meshes):
    found = []
    for obj in meshes:
        for slot in obj.material_slots:
            if slot.material == material:
                found.append(obj)
                break
    return found


def bake_surface_materials(scene, meshes):
    prepare_bake_color(scene)
    baked = []
    for name in BAKE_MATERIALS:
        mat = bpy.data.materials.get(name)
        if mat is None or not needs_bake(mat):
            print("BAKE_SKIP", name)
            continue
        users = objects_using(mat, meshes)
        if not users:
            print("BAKE_SKIP_UNUSED", name)
            continue
        node = principled_node(mat)
        rough_value = node.inputs["Roughness"].default_value
        metallic = node.inputs["Metallic"].default_value
        size = 2048 if name in HI_RES else 1024
        tile = 1.0
        plane = None
        try:
            plane = bake_plane(scene, mat, tile)
            color_img = new_bake_image(f"WEB {name} color", size, data=False)
            rough_img = new_bake_image(f"WEB {name} rough", size, data=True)
            normal_img = new_bake_image(f"WEB {name} normal", size, data=True)
            bake_pass(scene, plane, mat, color_img, "DIFFUSE", {"COLOR"})
            bake_pass(scene, plane, mat, rough_img, "ROUGHNESS", None)
            bake_pass(scene, plane, mat, normal_img, "NORMAL", None)
            assign_baked_material(mat, color_img, rough_img, normal_img, rough_value, metallic)
            project_uv(users, tile)
            baked.append(name)
            print("BAKE_OK", name, "objects", len(users), "px", size)
        except Exception as error:
            print("BAKE_FAIL", name, error)
        finally:
            if plane and plane.name in bpy.data.objects:
                mesh = plane.data
                bpy.data.objects.remove(plane, do_unlink=True)
                if mesh and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
    return baked


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
    baked = bake_surface_materials(scene, chosen)
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
        "materials_baked": baked,
        "bytes": size,
        "note": (
            "Промежуточная визуализация для просмотра объёма. "
            "Потолки скрыты, чтобы комнаты были видны сверху. "
            "Стены, пол, текстиль и орех запечены в карты для браузера; "
            "это не вид Cycles и не ведомость к закупке."
        ),
    }
    Path(info_path).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXPORT_OK", glb_path, size, "meshes", len(chosen))


if __name__ == "__main__":
    main()
