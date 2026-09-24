"""Zapisz natywny plik .blend ze sceny dołączonej do pakietu.

Skrypt wymaga Blendera, nie został uruchomiony w środowisku generującym pakiet.
Nie jest potrzebny do otwarcia dołączonych plików GLB.

Użycie z terminala:
  blender --background --python utworz_scene_Blender.py -- --root "/folder/dom_3d"

Alternatywnie otwórz ten plik w edytorze tekstu Blendera i uruchom Run Script.
Plik scena_modelu.json powinien leżeć obok skryptu. Nie usuwa istniejących scen.
Istniejący plik dom_model.blend nie zostanie nadpisany bez --overwrite.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import bpy
from mathutils import Vector


def main():
    default_root=Path(__file__).resolve().parent if '__file__' in globals() else Path.cwd()
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=default_root)
    parser.add_argument('--overwrite',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    root=args.root.resolve()
    output=root/'dom_model.blend'
    if output.exists() and not args.overwrite:
        raise FileExistsError(f'{output} już istnieje. Zmień nazwę lub świadomie użyj --overwrite.')
    source=root/'scena_modelu.json'
    if not source.is_file():
        raise FileNotFoundError(f'Brak {source}; rozpakuj cały pakiet do jednego folderu.')
    data=json.loads(source.read_text(encoding='utf-8'))
    scene=bpy.data.scenes.new('DOM_model_roboczy')
    if bpy.context.window:
        bpy.context.window.scene=scene
    scene.unit_settings.system='METRIC'
    scene.unit_settings.scale_length=1.0
    scene.unit_settings.length_unit='METERS'
    scene['source_document']='Projekt budowlany PZT_PAB_2024.02.01.pdf'
    scene['status']='Model roboczy; przyjęte wysokości i uproszczony dach: CZYTAJ_MNIE.md'
    scene['coordinate_system']='Metry, Z w górę; X i Y zgodne z rzędnymi rzutu źródłowego.'
    groups={
        'sciany':'01 Ściany i słup',
        'uzupelnienia':'02 Mur pod i nad otworami',
        'izolacja':'03 Izolacja zewnętrzna',
        'podlogi':'04 Podłogi — osobne powierzchnie',
        'stolarka':'05 Stolarka — symbole',
        'strop':'06 Strop — wyłącz do wnętrz',
        'dach':'07 Dach uproszczony — wyłącz do wnętrz',
        'sufity':'08 Sufity — poziom 2,60 m',
    }
    collections={}
    for category,name in groups.items():
        col=bpy.data.collections.new(name)
        scene.collection.children.link(col)
        col.hide_viewport=category in ['strop','dach','sufity']
        col.hide_render=col.hide_viewport
        collections[category]=col
    materials={}
    for part in data['parts']:
        # Każda podłoga pomieszczenia otrzymuje niezależny materiał.
        key=(part['source_id']+'_podloga') if part['category']=='podlogi' and part['source_id'].startswith('R') else part['material']
        if key not in materials:
            mat=bpy.data.materials.new(key)
            mat.diffuse_color=tuple(part['color'])
            mat.use_nodes=True
            node=mat.node_tree.nodes.get('Principled BSDF')
            node.inputs['Base Color'].default_value=tuple(part['color'])
            node.inputs['Roughness'].default_value=0.82
            if part['material']=='szklo':
                node.inputs['Alpha'].default_value=part['color'][3]
                if hasattr(mat,'surface_render_method'):
                    mat.surface_render_method='DITHERED'
            materials[key]=mat
        vertices=part['positions_m']
        center=Vector(tuple((part['bbox_mm'][0][i]+part['bbox_mm'][1][i])/2000 for i in range(3)))
        local=[tuple(Vector(v)-center) for v in vertices]
        mesh=bpy.data.meshes.new(part['name']+'_mesh')
        mesh.from_pydata(local,[],part['faces'])
        mesh.update()
        mesh.materials.append(materials[key])
        # Jednostkowe UV: długość 1 na mapie = 1 m w modelu.
        uv=mesh.uv_layers.new(name='UV_metry')
        for face in mesh.polygons:
            axis=max(range(3),key=lambda j:abs(face.normal[j]))
            axes=(1,2) if axis==0 else (0,2) if axis==1 else (0,1)
            for loop_index in face.loop_indices:
                vertex_index=mesh.loops[loop_index].vertex_index
                xyz=vertices[vertex_index]
                uv.data[loop_index].uv=(xyz[axes[0]],xyz[axes[1]])
        obj=bpy.data.objects.new(part['name'],mesh)
        obj.location=center
        collections[part['category']].objects.link(obj)
        for field in ['source','source_id','assumed','note','geometry','room_name','reported_area_m2']:
            if part.get(field) is not None:
                obj[field]=part[field]
    camera_data=bpy.data.cameras.new('Kamera_robocza')
    camera=bpy.data.objects.new('Kamera_robocza',camera_data)
    scene.collection.objects.link(camera)
    target=Vector((14.15,5.96,0.65))
    camera.location=(8,-22,28)
    camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO'
    camera_data.ortho_scale=34
    scene.camera=camera
    world=bpy.data.worlds.new('Swiatlo_robocze')
    world.use_nodes=True
    world.node_tree.nodes['Background'].inputs['Color'].default_value=(0.8,0.85,0.9,1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value=0.8
    scene.world=world
    light_data=bpy.data.lights.new('Swiatlo_robocze','AREA')
    light=bpy.data.objects.new('Swiatlo_robocze',light_data)
    scene.collection.objects.link(light)
    light.location=(6,-5,20)
    light.rotation_euler=(target-light.location).to_track_quat('-Z','Y').to_euler()
    light_data.energy=2500
    light_data.shape='DISK'
    light_data.size=14
    scene.render.resolution_x=1600
    scene.render.resolution_y=1000
    scene.render.resolution_percentage=100
    # Ustaw przyjazny widok startowy również w istniejących ekranach interfejsu.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                region=area.spaces.active.region_3d
                region.view_location=target
                region.view_rotation=camera.rotation_euler.to_quaternion()
                region.view_distance=34
                region.view_perspective='ORTHO'
                area.spaces.active.shading.color_type='MATERIAL'
                area.spaces.active.clip_end=1000
    for filename in ['CZYTAJ_MNIE.md','parametry_modelu.json']:
        textfile=root/filename
        if textfile.is_file():
            txt=bpy.data.texts.new(filename)
            txt.write(textfile.read_text(encoding='utf-8'))
    bpy.ops.wm.save_as_mainfile(filepath=str(output),compress=True)
    print(f'Zapisano {output}')

if __name__=='__main__':
    main()
