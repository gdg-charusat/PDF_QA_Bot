import React from "react";
import { Navbar, Container, Button } from "react-bootstrap";

/**
 * Header component - Displays navbar with title and theme toggle
 */
const Header = ({ darkMode, onThemeToggle }) => {
  return (
    <Navbar bg={darkMode ? "dark" : "primary"} variant="dark">
      <Container className="d-flex justify-content-between">
        <Navbar.Brand>🤖 PDF Q&A Bot</Navbar.Brand>
        <Button variant="outline-light" onClick={onThemeToggle}>
          {darkMode ? "Light" : "Dark"}
        </Button>
      </Container>
    </Navbar>
  );
};

export default Header;
