"""Definition of the lowest order RWG space."""

# pylint: disable=unused-argument

import numpy as _np
import numba as _numba

from .space import _FunctionSpace, _SpaceData, _process_segments


class Rwg0FunctionSpace(_FunctionSpace):
    """A space of RWG functions."""

    def __init__(
        self,
        grid,
        support_elements=None,
        segments=None,
        swapped_normals=None,
        include_boundary_dofs=False,
    ):
        """Initialize with a given grid."""
        from .localised_space import LocalisedFunctionSpace

        from scipy.sparse import coo_matrix

        shapeset = "rwg0"
        number_of_elements = grid.number_of_elements

        support, normal_mult = _process_segments(
            grid, support_elements, segments, swapped_normals
        )

        elements_in_support = _np.flatnonzero(support)

        local2global_map = _np.zeros((number_of_elements, 3), dtype="uint32")
        local_multipliers = _np.zeros((number_of_elements, 3), dtype="float64")
        edge_dofs = -_np.ones(grid.number_of_edges, dtype="int32")


        delete_from_support = []

        count = 0
        for element_index in elements_in_support:
            dofmap = -_np.ones(3, dtype="int32")
            for local_index in range(3):
                edge_index = grid.element_edges[local_index, element_index]
                edge_neighbors = grid.edge_neighbors[edge_index]

                if len(edge_neighbors) == 1:
                    other = -1  # There is no other neighbor
                else:
                    other = (
                        edge_neighbors[1]
                        if element_index == edge_neighbors[0]
                        else edge_neighbors[0]
                    )
                    if not support[other]:
                        # Neighbor element not in the support
                        other = -1

                if other == -1:
                    # We are at the boundary.
                    if not include_boundary_dofs:
                        local_multipliers[element_index, local_index] = 0
                    else:
                        local_multipliers[element_index, local_index] = 1
                        dofmap[local_index] = count
                        count += 1
                else:
                    # Assign 1 or -1 depending on element index
                    local_multipliers[element_index, local_index] = (
                        1 if element_index == min(edge_neighbors) else -1
                    )
                    if edge_dofs[edge_index] == -1:
                        edge_dofs[edge_index] = count
                        count += 1
                    dofmap[local_index] = edge_dofs[edge_index]

            # Check if no dof was assigned to element. In that case the element
            # needs to be deleted from the support.
            if _np.all(dofmap == -1):
                delete_from_support.append(element_index)
                local_multipliers[element_index, :] = 0
                local2global_map[element_index, :] = 0
            else:
                # For every zero local multiplier assign an existing global dof
                # in this element. This does not change the result as zero multipliers
                # do not contribute. But it allows us not to have to distinguish between
                # existing and non existing dofs later on.
                arg_zeros = _np.flatnonzero(local_multipliers[element_index] == 0)
                first_nonzero = _np.min(
                    _np.flatnonzero(local_multipliers[element_index] != 0)
                )
                dofmap[arg_zeros] = dofmap[first_nonzero]
                local2global_map[element_index, :] = dofmap

        global_dof_count = count

        for index in delete_from_support:
            support[index] = False

        support_size = _np.count_nonzero(support)

        if support_size == 0:
            raise ValueError("The support of the function space is empty.")

        codomain_dimension = 3
        order = 0
        identifier = "rwg0"

        localised_space = LocalisedFunctionSpace(
            grid,
            codomain_dimension,
            order,
            shapeset,
            3,
            identifier,
            support,
            normal_mult,
            self.numba_evaluate,
            None,
        )

        space_data = _SpaceData(
            grid,
            codomain_dimension,
            global_dof_count,
            order,
            shapeset,
            local2global_map,
            local_multipliers,
            identifier,
            support,
            localised_space,
            normal_mult
        )

        super().__init__(space_data)

    @property
    def numba_evaluate(self):
        """Return numba method that evaluates the basis."""
        return _numba_evaluate

    @property
    def numba_surface_gradient(self):
        """Return numba method that evaluates the surface gradient."""
        raise NotImplementedError

    def evaluate(self, element, local_coordinates):
        """Evaluate the basis on an element."""
        return _numba_evaluate(
            element.index,
            self.shapeset.evaluate,
            local_coordinates,
            self.grid.data,
            self.local_multipliers,
            self.normal_multipliers
        )

    def surface_gradient(self, element, local_coordinates):
        """Return the surface gradient."""
        raise NotImplementedError


@_numba.njit
def _numba_evaluate(
    element_index, shapeset_evaluate, local_coordinates, grid_data, local_multipliers, normal_multipliers
):
    """Evaluate the basis on an element."""
    reference_values = shapeset_evaluate(local_coordinates)
    npoints = local_coordinates.shape[1]
    result = _np.empty((3, 3, npoints), dtype=_np.float64)

    edge_lengths = _np.empty(3, dtype=_np.float64)
    edge_lengths[0] = _np.linalg.norm(
        grid_data.vertices[:, grid_data.elements[0, element_index]]
        - grid_data.vertices[:, grid_data.elements[1, element_index]]
    )
    edge_lengths[1] = _np.linalg.norm(
        grid_data.vertices[:, grid_data.elements[2, element_index]]
        - grid_data.vertices[:, grid_data.elements[0, element_index]]
    )
    edge_lengths[2] = _np.linalg.norm(
        grid_data.vertices[:, grid_data.elements[1, element_index]]
        - grid_data.vertices[:, grid_data.elements[2, element_index]]
    )

    for index in range(3):
        result[:, index, :] = (
            local_multipliers[element_index, index]
            * edge_lengths[index]
            / grid_data.integration_elements[element_index]
            * grid_data.jacobians[element_index].dot(reference_values[:, index, :])
        )
    return result
