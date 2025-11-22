
import requests
import json
import re
import time
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


@dataclass
class Color:
    r: float
    g: float
    b: float
    a: float = 1.0
    
    def to_css(self) -> str:
        
        r = int(self.r * 255)
        g = int(self.g * 255)
        b = int(self.b * 255)
        if self.a < 1.0:
            return f"rgba({r}, {g}, {b}, {self.a})"
        return f"rgb({r}, {g}, {b})"
    
    @classmethod
    def from_figma(cls, color_dict: Dict) -> 'Color':
        return cls(
            r=color_dict.get('r', 0),
            g=color_dict.get('g', 0),
            b=color_dict.get('b', 0),
            a=color_dict.get('a', 1.0)
        )


class FigmaAPI:
    
    BASE_URL = "https://api.figma.com/v1"
    MAX_RETRIES = 5
    INITIAL_BACKOFF = 1
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "X-Figma-Token": access_token
        }
    
    def _make_request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.request(method, url, headers=self.headers, **kwargs)
                
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        wait_time = int(retry_after)
                    else:
                        wait_time = self.INITIAL_BACKOFF * (2 ** attempt)
                    
                    if attempt < self.MAX_RETRIES - 1:
                        print(f"Rate limit hit (429). Waiting {wait_time} seconds before retry {attempt + 1}/{self.MAX_RETRIES}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        response.raise_for_status()
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES - 1:
                    wait_time = self.INITIAL_BACKOFF * (2 ** attempt)
                    print(f"Request failed: {e}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise
        
        response.raise_for_status()
        return response
    
    def get_file(self, file_key: str) -> Dict:
        url = f"{self.BASE_URL}/files/{file_key}"
        response = self._make_request_with_retry('GET', url)
        return response.json()
    
    def get_images(self, file_key: str, node_ids: List[str], 
                   scale: float = 2.0, format: str = "png") -> Dict:
        url = f"{self.BASE_URL}/images/{file_key}"
        params = {
            "ids": ",".join(node_ids),
            "scale": scale,
            "format": format
        }
        response = self._make_request_with_retry('GET', url, params=params)
        return response.json()


class FigmaToHTMLConverter:
    def __init__(self, figma_data: Dict):
        self.figma_data = figma_data
        self.document = figma_data.get('document', {})
        self.components = figma_data.get('components', {})
        self.styles = figma_data.get('styles', {})
        self.css_classes = []
        self.class_counter = 0
        self.fonts_used = set()
        self.root_frame_bbox = None  
        self.node_positions = {}
    
    def convert(self) -> Tuple[str, str]:
        html_parts = []
        
        for page in self.document.get('children', []):
            if page.get('type') == 'CANVAS':
                page_html = self.process_canvas(page)
                if page_html:
                    html_parts.append(page_html)
        
        html = self.build_html_document('\n'.join(html_parts))
        css = self.build_css()
        
        return html, css
    
    def process_canvas(self, canvas: Dict) -> str:
        html_parts = []
        
        for child in canvas.get('children', []):
            if child.get('type') in ['FRAME', 'COMPONENT', 'INSTANCE']:
                bbox = child.get('absoluteBoundingBox', {})
                if bbox:
                    if self.root_frame_bbox is None:
                        self.root_frame_bbox = bbox
                    else:
                        current_area = bbox.get('width', 0) * bbox.get('height', 0)
                        root_area = self.root_frame_bbox.get('width', 0) * self.root_frame_bbox.get('height', 0)
                        if current_area > root_area:
                            self.root_frame_bbox = bbox
                    break
        
        for child in canvas.get('children', []):
            child_html = self.process_node(child, None, None)
            if child_html:
                html_parts.append(child_html)
        
        return '\n'.join(html_parts)
    
    def process_node(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        node_type = node.get('type')
        
        if not node.get('visible', True):
            return ''
        
        node_bbox = node.get('absoluteBoundingBox', {})
        if node_bbox:
            node_id = node.get('id', '')
            self.node_positions[node_id] = node_bbox
        
        handlers = {
            'FRAME': self.process_frame,
            'GROUP': self.process_group,
            'RECTANGLE': self.process_rectangle,
            'ELLIPSE': self.process_ellipse,
            'TEXT': self.process_text,
            'VECTOR': self.process_vector,
            'INSTANCE': self.process_instance,
            'COMPONENT': self.process_component,
            'BOOLEAN_OPERATION': self.process_boolean_operation,
            'STAR': self.process_star,
            'POLYGON': self.process_polygon,
            'LINE': self.process_line,
        }
        
        handler = handlers.get(node_type)
        if handler:
            return handler(node, parent_type, parent_bbox)
        
        if 'children' in node:
            return self.process_container(node, parent_type, parent_bbox)
        
        return ''
    
    def process_frame(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'frame'))
        node_bbox = node.get('absoluteBoundingBox', {})
        
        is_root_frame = False
        if self.root_frame_bbox and node_bbox:
            root_x = self.root_frame_bbox.get('x', 0)
            root_y = self.root_frame_bbox.get('y', 0)
            root_w = self.root_frame_bbox.get('width', 0)
            root_h = self.root_frame_bbox.get('height', 0)
            
            node_x = node_bbox.get('x', 0)
            node_y = node_bbox.get('y', 0)
            node_w = node_bbox.get('width', 0)
            node_h = node_bbox.get('height', 0)
            
            is_root_frame = (abs(node_x - root_x) < 0.001 and 
                            abs(node_y - root_y) < 0.001 and
                            abs(node_w - root_w) < 0.001 and
                            abs(node_h - root_h) < 0.001)
        
        styles = self.extract_node_styles(node, parent_bbox, is_root_frame)
        
        layout_mode = node.get('layoutMode')
        if layout_mode == 'HORIZONTAL':
            styles['display'] = 'flex'
            styles['flex-direction'] = 'row'
        elif layout_mode == 'VERTICAL':
            styles['display'] = 'flex'
            styles['flex-direction'] = 'column'
        
        self.add_layout_properties(node, styles)
        
        if 'border-radius' not in styles:
            corner_radius = node.get('cornerRadius', 0)
            if corner_radius:
                styles['border-radius'] = f'{corner_radius}px'
            
            individual_radii = []
            for corner in ['rectangleTopLeftCornerRadius', 'rectangleTopRightCornerRadius',
                          'rectangleBottomRightCornerRadius', 'rectangleBottomLeftCornerRadius']:
                radius = node.get(corner)
                if radius is not None:
                    individual_radii.append(f'{radius}px')
            
            if len(individual_radii) == 4:
                styles['border-radius'] = ' '.join(individual_radii)
        
        children_html = []
        has_children = bool(node.get('children', []))
        
        fills = node.get('fills', [])
        has_gradient = any(f.get('type') in ['GRADIENT_LINEAR', 'GRADIENT_RADIAL', 'GRADIENT_ANGULAR'] 
                          for f in fills if f.get('visible', True))
        has_solid_bg = any(f.get('type') == 'SOLID' for f in fills if f.get('visible', True))
        
        if (has_gradient or has_solid_bg) and has_children:
            if 'display' not in styles:
                styles['display'] = 'flex'
            if 'justify-content' not in styles:
                styles['justify-content'] = 'center'
            if 'align-items' not in styles:
                styles['align-items'] = 'center'
        
        if has_children and not is_root_frame:
            if 'position' not in styles:
                styles['position'] = 'relative'
        
        for child in node.get('children', []):
            child_html = self.process_node(child, 'FRAME', node_bbox)
            if child_html:
                children_html.append(child_html)
        
        self.add_css_class(class_name, styles)
        
        tag = 'div'
        return f'<{tag} class="{class_name}">\n{"".join(children_html)}</{tag}>'
    
    def process_group(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'group'))
        node_bbox = node.get('absoluteBoundingBox', {})
        styles = self.extract_node_styles(node, parent_bbox, False, include_bg=False)
        
        children_html = []
        for child in node.get('children', []):
            child_html = self.process_node(child, 'GROUP', node_bbox)
            if child_html:
                children_html.append(child_html)
        
        self.add_css_class(class_name, styles)
        
        return f'<div class="{class_name}">\n{"".join(children_html)}</div>'
    
    def process_rectangle(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'rectangle'))
        styles = self.extract_node_styles(node, parent_bbox)
        
        corner_radius = node.get('cornerRadius', 0)
        if corner_radius:
            styles['border-radius'] = f'{corner_radius}px'
        
        individual_radii = []
        for corner in ['rectangleTopLeftCornerRadius', 'rectangleTopRightCornerRadius',
                      'rectangleBottomRightCornerRadius', 'rectangleBottomLeftCornerRadius']:
            radius = node.get(corner)
            if radius is not None:
                individual_radii.append(f'{radius}px')
        
        if len(individual_radii) == 4:
            styles['border-radius'] = ' '.join(individual_radii)
        
        self.add_css_class(class_name, styles)
        
        node_bbox = node.get('absoluteBoundingBox', {})
        children_html = []
        for child in node.get('children', []):
            child_html = self.process_node(child, 'RECTANGLE', node_bbox)
            if child_html:
                children_html.append(child_html)
        
        if children_html:
            return f'<div class="{class_name}">{"".join(children_html)}</div>'
        return f'<div class="{class_name}"></div>'
    
    def process_ellipse(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'ellipse'))
        styles = self.extract_node_styles(node, parent_bbox)
        styles['border-radius'] = '50%'
        
        self.add_css_class(class_name, styles)
        
        return f'<div class="{class_name}"></div>'
    
    def process_text(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'text'))
        styles = self.extract_node_styles(node, parent_bbox, False, include_bg=False)
        
        style = node.get('style', {})
        
        style_overrides = node.get('styleOverrideTable', {})
        if style_overrides:
            for key, value in style_overrides.items():
                if value:
                    style[key] = value
        
        fills = node.get('fills', [])
        if not fills:
            pass
        
        if 'fontFamily' in style:
            font_family = style['fontFamily']
            self.fonts_used.add(font_family)
            styles['font-family'] = f'"{font_family}", sans-serif'
        
        if 'fontSize' in style:
            styles['font-size'] = f"{style['fontSize']}px"
        
        if 'fontWeight' in style:
            styles['font-weight'] = str(style['fontWeight'])
        
        if 'italic' in style and style['italic']:
            styles['font-style'] = 'italic'
        elif 'fontStyle' in style:
            font_style = style['fontStyle']
            if 'italic' in font_style.lower():
                styles['font-style'] = 'italic'
        
        if 'letterSpacing' in style:
            letter_spacing = style['letterSpacing']
            if isinstance(letter_spacing, dict):
                if letter_spacing.get('unit') == 'PERCENT':
                    styles['letter-spacing'] = f"{letter_spacing['value'] / 100}em"
                else:
                    styles['letter-spacing'] = f"{letter_spacing['value']}px"
            else:
                styles['letter-spacing'] = f"{letter_spacing}px"
        
        if 'lineHeightPx' in style:
            styles['line-height'] = f"{style['lineHeightPx']}px"
        elif 'lineHeightPercent' in style:
            styles['line-height'] = f"{style['lineHeightPercent']}%"
        elif 'lineHeightPercentFontSize' in style:
            font_size = style.get('fontSize', 16)
            line_height_percent = style['lineHeightPercentFontSize']
            styles['line-height'] = f"{font_size * line_height_percent / 100}px"
        
        if 'textAlignHorizontal' in style:
            align = style['textAlignHorizontal'].lower()
            if align in ['left', 'center', 'right', 'justified']:
                styles['text-align'] = 'justify' if align == 'justified' else align
                if align == 'center':
                    if 'left' in styles:
                        pass
        
        if 'textAlignVertical' in style:
            align = style['textAlignVertical'].lower()
            if align == 'center':
                styles['display'] = 'flex'
                styles['align-items'] = 'center'
        
        if 'textDecoration' in style:
            decoration = style['textDecoration'].lower()
            if decoration != 'none':
                styles['text-decoration'] = decoration.replace('_', '-')
        
        if 'textCase' in style:
            case = style['textCase'].lower()
            if case == 'upper':
                styles['text-transform'] = 'uppercase'
            elif case == 'lower':
                styles['text-transform'] = 'lowercase'
            elif case == 'title':
                styles['text-transform'] = 'capitalize'
        
        if fills and len(fills) > 0:
            fill = fills[0]
            if fill.get('type') == 'SOLID' and 'color' in fill:
                color = Color.from_figma(fill['color'])
                color.a = fill.get('opacity', 1.0)
                styles['color'] = color.to_css()
        
        self.add_css_class(class_name, styles)
        
        text_content = node.get('characters', '')
        text_content = text_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        tag = 'span'
        if style.get('fontSize', 0) > 24:
            tag = 'h2'
        elif style.get('fontWeight', 400) >= 600:
            tag = 'strong'
        
        return f'<{tag} class="{class_name}">{text_content}</{tag}>'
    
    def process_vector(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'vector'))
        styles = self.extract_node_styles(node, parent_bbox)
        
        self.add_css_class(class_name, styles)
        
        return f'<div class="{class_name}"></div>'
    
    def process_instance(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        return self.process_frame(node, parent_type, parent_bbox)
    
    def process_component(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        return self.process_frame(node, parent_type, parent_bbox)
    
    def process_boolean_operation(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        return self.process_vector(node, parent_type, parent_bbox)
    
    def process_star(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        return self.process_vector(node, parent_type, parent_bbox)
    
    def process_polygon(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        return self.process_vector(node, parent_type, parent_bbox)
    
    def process_line(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'line'))
        styles = self.extract_node_styles(node, parent_bbox, False, include_bg=False)
        
        strokes = node.get('strokes', [])
        if strokes:
            stroke = strokes[0]
            if stroke.get('type') == 'SOLID':
                color = Color.from_figma(stroke['color'])
                styles['background-color'] = color.to_css()
        
        self.add_css_class(class_name, styles)
        
        return f'<div class="{class_name}"></div>'
    
    def process_container(self, node: Dict, parent_type: str = None, parent_bbox: Dict = None) -> str:
        class_name = self.generate_class_name(node.get('name', 'container'))
        styles = self.extract_node_styles(node, parent_bbox)
        
        node_bbox = node.get('absoluteBoundingBox', {})
        children_html = []
        for child in node.get('children', []):
            child_html = self.process_node(child, node.get('type'), node_bbox)
            if child_html:
                children_html.append(child_html)
        
        self.add_css_class(class_name, styles)
        
        return f'<div class="{class_name}">{"".join(children_html)}</div>'
    
    def extract_node_styles(self, node: Dict, parent_bbox: Dict = None, is_root_frame: bool = False, include_bg: bool = True) -> Dict[str, str]:
        styles = {}
        
        bbox = node.get('absoluteBoundingBox', {})
        if bbox:
            x = bbox.get('x', 0)
            y = bbox.get('y', 0)
            width = bbox.get('width', 0)
            height = bbox.get('height', 0)
            
            x = 0 if abs(x) < 0.001 else x
            y = 0 if abs(y) < 0.001 else y
            
            if is_root_frame:
                styles['position'] = 'relative'
                styles['margin'] = '0 auto'
                styles['width'] = f"{width}px"
                styles['height'] = f"{height}px"
                corner_radius = node.get('cornerRadius', 0)
                if corner_radius:
                    styles['border-radius'] = f'{corner_radius}px'
                else:
                    styles['border-radius'] = '24px'
                styles['overflow'] = 'hidden'
            elif parent_bbox:
                parent_x = parent_bbox.get('x', 0)
                parent_y = parent_bbox.get('y', 0)
                parent_width = parent_bbox.get('width', 0)
                
                rel_x = x - parent_x
                rel_y = y - parent_y
                
                node_type = node.get('type', '')
                if node_type == 'TEXT':
                    text_style = node.get('style', {})
                    text_align = text_style.get('textAlignHorizontal', '').lower()
                    if text_align == 'center':
                        text_center_x = rel_x + (width / 2)
                        parent_center_x = parent_width / 2
                        if abs(text_center_x - parent_center_x) < 20:
                            styles['position'] = 'absolute'
                            styles['left'] = '50%'
                            styles['top'] = f"{rel_y}px"
                            styles['transform'] = 'translateX(-50%)'
                            styles['width'] = 'auto'
                            styles['height'] = f"{height}px"
                        else:
                            styles['position'] = 'absolute'
                            styles['left'] = f"{rel_x}px"
                            styles['top'] = f"{rel_y}px"
                            styles['width'] = f"{width}px"
                            styles['height'] = f"{height}px"
                    else:
                        styles['position'] = 'absolute'
                        styles['left'] = f"{rel_x}px"
                        styles['top'] = f"{rel_y}px"
                        styles['width'] = f"{width}px"
                        styles['height'] = f"{height}px"
                else:
                    styles['position'] = 'absolute'
                    styles['left'] = f"{rel_x}px"
                    styles['top'] = f"{rel_y}px"
                    styles['width'] = f"{width}px"
                    styles['height'] = f"{height}px"
            else:
                styles['position'] = 'absolute'
                styles['left'] = f"{x}px"
                styles['top'] = f"{y}px"
                styles['width'] = f"{width}px"
                styles['height'] = f"{height}px"
        
        opacity = node.get('opacity')
        if opacity is not None and opacity < 1.0:
            styles['opacity'] = str(opacity)
        
        if include_bg:
            fills = node.get('fills', [])
            if fills:
                self.process_fills(fills, styles)
        
        strokes = node.get('strokes', [])
        if strokes:
            self.process_strokes(node, strokes, styles)
        
        effects = node.get('effects', [])
        if effects:
            self.process_effects(effects, styles)
        
        blend_mode = node.get('blendMode')
        if blend_mode and blend_mode != 'NORMAL':
            css_blend = self.convert_blend_mode(blend_mode)
            if css_blend:
                styles['mix-blend-mode'] = css_blend
        
        constraints = node.get('constraints')
        if constraints:
            self.process_constraints(constraints, styles)
        
        return styles
    
    def process_fills(self, fills: List[Dict], styles: Dict[str, str]):
        visible_fills = [f for f in fills if f.get('visible', True)]
        if not visible_fills:
            return
        
        if len(visible_fills) == 1:
            fill = visible_fills[0]
            fill_type = fill.get('type')
            
            if fill_type == 'SOLID':
                color = Color.from_figma(fill['color'])
                color.a = fill.get('opacity', 1.0)
                styles['background-color'] = color.to_css()
            
            elif fill_type in ['GRADIENT_LINEAR', 'GRADIENT_RADIAL', 'GRADIENT_ANGULAR']:
                gradient = self.create_gradient(fill)
                if gradient:
                    styles['background'] = gradient
            
            elif fill_type == 'IMAGE':
                styles['background-size'] = 'cover'
                styles['background-position'] = 'center'
        else:
            backgrounds = []
            for fill in reversed(visible_fills):
                if fill.get('type') == 'SOLID':
                    color = Color.from_figma(fill['color'])
                    color.a = fill.get('opacity', 1.0)
                    backgrounds.append(color.to_css())
                elif fill.get('type') in ['GRADIENT_LINEAR', 'GRADIENT_RADIAL']:
                    gradient = self.create_gradient(fill)
                    if gradient:
                        backgrounds.append(gradient)
            
            if backgrounds:
                styles['background'] = ', '.join(backgrounds)
    
    def create_gradient(self, fill: Dict) -> Optional[str]:
        gradient_type = fill.get('type')
        gradient_stops = fill.get('gradientStops', [])
        
        if not gradient_stops:
            return None
        
        stops = []
        for stop in gradient_stops:
            color = Color.from_figma(stop['color'])
            position = stop.get('position', 0) * 100
            stops.append(f"{color.to_css()} {position}%")
        
        stops_str = ', '.join(stops)
        
        if gradient_type == 'GRADIENT_LINEAR':
            handles = fill.get('gradientHandlePositions', [])
            if len(handles) >= 2:
                return f"linear-gradient(90deg, {stops_str})"
            return f"linear-gradient(180deg, {stops_str})"
        
        elif gradient_type == 'GRADIENT_RADIAL':
            return f"radial-gradient(circle, {stops_str})"
        
        elif gradient_type == 'GRADIENT_ANGULAR':
            return f"conic-gradient({stops_str})"
        
        return None
    
    def process_strokes(self, node: Dict, strokes: List[Dict], styles: Dict[str, str]):
        visible_strokes = [s for s in strokes if s.get('visible', True)]
        if not visible_strokes:
            return
        
        stroke = visible_strokes[0]
        stroke_weight = node.get('strokeWeight', 1)
        stroke_align = node.get('strokeAlign', 'INSIDE')
        
        if stroke.get('type') == 'SOLID':
            color = Color.from_figma(stroke['color'])
            color.a = stroke.get('opacity', 1.0)
            
            styles['border-style'] = 'solid'
            styles['border-width'] = f'{stroke_weight}px'
            styles['border-color'] = color.to_css()
            
            if stroke_align == 'CENTER':
                pass
            elif stroke_align == 'OUTSIDE':
                styles['outline'] = f"{stroke_weight}px solid {color.to_css()}"
                del styles['border-style']
                del styles['border-width']
                del styles['border-color']
        
        stroke_dashes = node.get('strokeDashes')
        if stroke_dashes and len(stroke_dashes) > 0:
            dash_pattern = ' '.join(str(d) for d in stroke_dashes)
            styles['border-style'] = 'dashed' if len(stroke_dashes) == 2 else 'dotted'
    
    def process_effects(self, effects: List[Dict], styles: Dict[str, str]):
        shadows = []
        
        for effect in effects:
            if not effect.get('visible', True):
                continue
            
            effect_type = effect.get('type')
            
            if effect_type == 'DROP_SHADOW':
                offset_x = effect.get('offset', {}).get('x', 0)
                offset_y = effect.get('offset', {}).get('y', 0)
                radius = effect.get('radius', 0)
                color = Color.from_figma(effect.get('color', {}))
                
                shadow = f"{offset_x}px {offset_y}px {radius}px {color.to_css()}"
                shadows.append(shadow)
            
            elif effect_type == 'INNER_SHADOW':
                offset_x = effect.get('offset', {}).get('x', 0)
                offset_y = effect.get('offset', {}).get('y', 0)
                radius = effect.get('radius', 0)
                color = Color.from_figma(effect.get('color', {}))
                
                shadow = f"inset {offset_x}px {offset_y}px {radius}px {color.to_css()}"
                shadows.append(shadow)
            
            elif effect_type == 'LAYER_BLUR':
                blur_radius = effect.get('radius', 0)
                styles['filter'] = f"blur({blur_radius}px)"
            
            elif effect_type == 'BACKGROUND_BLUR':
                blur_radius = effect.get('radius', 0)
                styles['backdrop-filter'] = f"blur({blur_radius}px)"
        
        if shadows:
            styles['box-shadow'] = ', '.join(shadows)
    
    def add_layout_properties(self, node: Dict, styles: Dict[str, str]):
        padding_left = node.get('paddingLeft', 0)
        padding_right = node.get('paddingRight', 0)
        padding_top = node.get('paddingTop', 0)
        padding_bottom = node.get('paddingBottom', 0)
        
        if padding_left or padding_right or padding_top or padding_bottom:
            if padding_left == padding_right == padding_top == padding_bottom:
                styles['padding'] = f'{padding_left}px'
            else:
                styles['padding'] = f'{padding_top}px {padding_right}px {padding_bottom}px {padding_left}px'
        
        item_spacing = node.get('itemSpacing')
        if item_spacing:
            styles['gap'] = f'{item_spacing}px'
        
        primary_align = node.get('primaryAxisAlignItems')
        counter_align = node.get('counterAxisAlignItems')
        
        if primary_align:
            align_map = {
                'MIN': 'flex-start',
                'CENTER': 'center',
                'MAX': 'flex-end',
                'SPACE_BETWEEN': 'space-between'
            }
            styles['justify-content'] = align_map.get(primary_align, 'flex-start')
        
        if counter_align:
            align_map = {
                'MIN': 'flex-start',
                'CENTER': 'center',
                'MAX': 'flex-end',
                'BASELINE': 'baseline'
            }
            styles['align-items'] = align_map.get(counter_align, 'flex-start')
    
    def process_constraints(self, constraints: Dict, styles: Dict[str, str]):
        pass
    
    def convert_blend_mode(self, figma_blend: str) -> Optional[str]:
        blend_map = {
            'PASS_THROUGH': 'normal',
            'MULTIPLY': 'multiply',
            'SCREEN': 'screen',
            'OVERLAY': 'overlay',
            'DARKEN': 'darken',
            'LIGHTEN': 'lighten',
            'COLOR_DODGE': 'color-dodge',
            'COLOR_BURN': 'color-burn',
            'HARD_LIGHT': 'hard-light',
            'SOFT_LIGHT': 'soft-light',
            'DIFFERENCE': 'difference',
            'EXCLUSION': 'exclusion',
            'HUE': 'hue',
            'SATURATION': 'saturation',
            'COLOR': 'color',
            'LUMINOSITY': 'luminosity'
        }
        return blend_map.get(figma_blend)
    
    def generate_class_name(self, name: str) -> str:
        clean_name = re.sub(r'[^a-zA-Z0-9-_]', '-', name)
        clean_name = re.sub(r'-+', '-', clean_name)
        clean_name = clean_name.strip('-').lower()
        
        if clean_name and clean_name[0].isdigit():
            clean_name = f'n-{clean_name}'
        
        self.class_counter += 1
        return f'{clean_name}-{self.class_counter}'
    
    def add_css_class(self, class_name: str, styles: Dict[str, str]):
        if styles:
            self.css_classes.append((class_name, styles))
    
    def build_css(self) -> str:
        css_parts = [
            "* {",
            "  margin: 0;",
            "  padding: 0;",
            "  box-sizing: border-box;",
            "}",
            "",
            "html, body {",
            "  margin: 0;",
            "  padding: 0;",
            "  width: 100%;",
            "  height: 100%;",
            "  overflow-x: hidden;",
            "}",
            "",
            "body {",
            "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;",
            "  position: relative;",
            "  display: flex;",
            "  justify-content: center;",
            "  align-items: center;",
            "  min-height: 100vh;",
            "  background-color: rgb(200, 200, 200);",
            "}",
            ""
        ]
        
        if self.fonts_used:
            fonts_query = '|'.join(f.replace(' ', '+') for f in self.fonts_used)
            css_parts.insert(0, f"@import url('https://fonts.googleapis.com/css2?family={fonts_query}&display=swap');")
            css_parts.insert(1, "")
        
        for class_name, styles in self.css_classes:
            css_parts.append(f'.{class_name} {{')
            for prop, value in styles.items():
                css_parts.append(f'  {prop}: {value};')
            css_parts.append('}')
            css_parts.append('')
        
        return '\n'.join(css_parts)
    
    def build_html_document(self, body_content: str) -> str:
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Figma Design Export</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
{body_content}
</body>
</html>'''


def main():
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python figma_to_html.py <figma_access_token> <file_key>")
        print("\nTo get your access token:")
        print("1. Go to Figma Settings > Account > Personal Access Tokens")
        print("2. Generate a new token")
        print("\nTo get the file key:")
        print("3. Copy your Figma file to your workspace")
        print("4. Extract the key from the URL: figma.com/file/<FILE_KEY>/...")
        sys.exit(1)
    
    access_token = sys.argv[1]
    file_key = sys.argv[2]
    
    print(f"Fetching Figma file...")
    
    api = FigmaAPI(access_token)
    try:
        figma_data = api.get_file(file_key)
    except Exception as e:
        print(f"Error fetching Figma file: {e}")
        sys.exit(1)
    
    print("Converting to HTML/CSS...")
    
    converter = FigmaToHTMLConverter(figma_data)
    html, css = converter.convert()
    
    with open('output.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    with open('styles.css', 'w', encoding='utf-8') as f:
        f.write(css)
    
    print("✓ Conversion complete!")
    print("  - output.html")
    print("  - styles.css")
    print(f"\nProcessed {len(converter.css_classes)} elements")
    if converter.fonts_used:
        print(f"Fonts used: {', '.join(converter.fonts_used)}")


if __name__ == '__main__':
    main()