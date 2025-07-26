
# To run this script, save it as a Python file (e.g., reflection_animation.py)
# and run the following command in your terminal:
# manim -pql reflection_animation.py LawsOfReflection

from manim import *
import numpy as np

class LawsOfReflection(Scene):
    """
    An animation to teach the Laws of Reflection using Manim.
    """
    def construct(self):
        # -----------------------------------------------------------------
        # 1. Introduction Title
        # -----------------------------------------------------------------
        title = Text("The Laws of Reflection", font_size=60)
        self.play(Write(title))
        self.wait(1.5)
        self.play(FadeOut(title))
        self.wait(0.5)

        # -----------------------------------------------------------------
        # 2. Setup the Scene: Mirror, Normal, Point of Incidence
        # -----------------------------------------------------------------
        
        # Define coordinates and objects
        mirror_level = -2.5
        poi_coords = np.array([0, mirror_level, 0]) # Point of Incidence
        ray_length = 3.5

        # Create the mirror
        mirror = Line(LEFT * 5, RIGHT * 5, color=BLUE_A, stroke_width=6).move_to(poi_coords + DOWN * 0.25)
        mirror_label = Text("Plane Mirror", font_size=24).next_to(mirror, DOWN, buff=0.2)

        # Create the normal line (perpendicular to the mirror)
        normal = DashedLine(
            poi_coords,
            poi_coords + UP * ray_length,
            color=WHITE
        )
        normal_label = Text("Normal", font_size=24).next_to(normal, RIGHT, buff=0.2).shift(LEFT*0.5)

        # Create the point of incidence
        poi_dot = Dot(poi_coords, color=YELLOW, radius=0.1)

        # Animate the setup
        self.play(Create(mirror), Write(mirror_label))
        self.play(Create(normal), Write(normal_label))
        self.play(FadeIn(poi_dot, scale=1.5))
        self.wait(1)

        # -----------------------------------------------------------------
        # 3. Introduce Rays and Angles (Static Demonstration)
        # -----------------------------------------------------------------
        
        # We use a ValueTracker to easily manage the angle (in radians)
        angle_tracker = ValueTracker(np.deg2rad(60))

        # Create the rays
        # The incident ray points towards the point of incidence
        incident_ray = Arrow(
            color=RED,
            buff=0,
            stroke_width=5
        )
        # The reflected ray points away from the point of incidence
        reflected_ray = Arrow(
            color=GREEN,
            buff=0,
            stroke_width=5
        )
        # We need a line representation of the incident ray pointing *away*
        # from the POI for the Angle mobject to work correctly. This won't be displayed.
        rev_incident_line = Line()

        # Create the angles
        angle_i = Angle(normal, rev_incident_line, radius=0.9, color=RED)
        angle_r = Angle(normal, reflected_ray, radius=0.9, color=GREEN)
        
        # Create angle labels
        label_i = MathTex("i", color=RED, font_size=36)
        label_r = MathTex("r", color=GREEN, font_size=36)
        
        # Group ray and angle labels for easier management
        incident_group_text = VGroup(
            Text("Incident Ray", color=RED, font_size=28),
            Text("Angle of Incidence (i)", color=RED, font_size=28)
        ).arrange(DOWN, aligned_edge=LEFT).to_corner(UL)

        reflected_group_text = VGroup(
            Text("Reflected Ray", color=GREEN, font_size=28),
            Text("Angle of Reflection (r)", color=GREEN, font_size=28)
        ).arrange(DOWN, aligned_edge=LEFT).to_corner(UR)

        # Updater functions to keep everything in sync with the angle_tracker
        def update_all_elements(m):
            # Get current angle
            angle = angle_tracker.get_value()
            
            # Calculate start/end points of rays
            start_point = poi_coords + ray_length * np.array([-np.sin(angle), np.cos(angle), 0])
            end_point = poi_coords + ray_length * np.array([np.sin(angle), np.cos(angle), 0])
            
            # Update rays
            incident_ray.put_start_and_end_on(start_point, poi_coords)
            reflected_ray.put_start_and_end_on(poi_coords, end_point)
            rev_incident_line.put_start_and_end_on(poi_coords, start_point)
            
            # Update angles
            angle_i.become(Angle(normal, rev_incident_line, radius=0.9, color=RED))
            angle_r.become(Angle(normal, reflected_ray, radius=0.9, color=GREEN))

            # Update labels
            # Position labels just outside the midpoint of their respective angle arcs
            label_i.move_to(angle_i.point_from_proportion(0.5) + (angle_i.point_from_proportion(0.5) - poi_coords) * 0.2)
            label_r.move_to(angle_r.point_from_proportion(0.5) + (angle_r.point_from_proportion(0.5) - poi_coords) * 0.2)

        # Add the updater to a dummy mobject that we add to the scene
        # This ensures the updater runs on every frame.
        self.add(Mobject().add_updater(update_all_elements))
        # Run the updater once to set initial positions
        update_all_elements(None)

        # Animate the appearance of rays and labels
        self.play(
            Create(incident_ray),
            Write(incident_group_text[0])
        )
        self.wait(0.5)
        self.play(
            Create(reflected_ray),
            Write(reflected_group_text[0])
        )
        self.wait(1)
        self.play(
            Create(angle_i), Write(label_i),
            Write(incident_group_text[1])
        )
        self.wait(0.5)
        self.play(
            Create(angle_r), Write(label_r),
            Write(reflected_group_text[1])
        )
        self.wait(2)

        # -----------------------------------------------------------------
        # 4. State the Laws
        # -----------------------------------------------------------------

        # Law 1
        law1_text = Tex(
            r"1. The incident ray, the reflected ray, and the normal \\ all lie in the same plane.",
            font_size=36
        ).to_edge(UP)
        self.play(Write(law1_text))
        self.wait(3)
        self.play(FadeOut(law1_text))
        
        # Law 2
        law2_text = Tex(
            r"2. The angle of incidence is equal to the angle of reflection.",
            font_size=36
        ).to_edge(UP)
        formula = MathTex(r"\angle i = \angle r", font_size=48).next_to(law2_text, DOWN, buff=0.4)
        
        self.play(Write(law2_text))
        self.play(Write(formula))
        self.wait(3)
        
        # -----------------------------------------------------------------
        # 5. Dynamic Demonstration
        # -----------------------------------------------------------------
        
        # Prepare for dynamic demo by fading out descriptive text
        self.play(
            FadeOut(incident_group_text, reflected_group_text),
            VGroup(law2_text, formula).animate.to_edge(UP, buff=0.5)
        )
        self.wait(1)

        # Animate the angle changing, demonstrating that i always equals r
        self.play(
            angle_tracker.animate.set_value(np.deg2rad(30)),
            run_time=3,
            rate_func=smooth
        )
        self.wait(1)
        self.play(
            angle_tracker.animate.set_value(np.deg2rad(75)),
            run_time=4,
            rate_func=smooth
        )
        self.wait(1)
        self.play(
            angle_tracker.animate.set_value(np.deg2rad(45)),
            run_time=2,
            rate_func=smooth
        )
        self.wait(2)

        # -----------------------------------------------------------------
        # 6. Conclusion
        # -----------------------------------------------------------------
        
        # Fade out all elements
        self.play(
            FadeOut(*self.mobjects)
        )
        self.wait(1)
        
        # Final message (optional)
        # thanks = Text("Thank you for watching!", font_size=48)
        # self.play(Write(thanks))
        # self.wait(2)
